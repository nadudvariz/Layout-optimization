# algorithms/evolution_strategy_algorithm.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
import random, time, math, copy
from schemas.heuristic_schema import HEURISTICS_REGISTRY
from models import ModelParams, Room
from util.io_evolution import save_the_indiv
from algorithms.algorithms_common import (create_relation_df, _effective_size_for_individual,
    random_center_in_container, preferred_container_side_for_component, compute_reserved_zone, build_structure_graph,)

Individual = List[Dict[str, Any]]

class ES_algorithm:
    def __init__(self, objects: List[Dict[str, Any]], room: Room, project_name: str,
                 solution_name: str, heuristics: List[Dict[str, Any]] | None = None,
                 constraints: List[Dict[str, Any]] | None = None,
                 init_population: List[Individual] | None = None, init_population_file: str = None, fitness=None,
                 overlap_enabled = False, wallfit_enabled = False, log_mode = False, results_dir: str | None = None):
        self.objects = objects
        self.room = room
        self.project_name = project_name
        self.solution_name = solution_name
        self.heuristics = heuristics or HEURISTICS_REGISTRY
        self.constraints = constraints
        self.init_population = init_population
        self.init_population_file = init_population_file

        # fitnessfunction wrapper
        self.fitness = fitness.calculate_weight_sum
        self.fitness_count = fitness.get_usages

        self.overlap_enabled = overlap_enabled
        self.wallfit_enabled = wallfit_enabled
        self.log_mode = log_mode
        self.results_dir = results_dir

        # create_relation_df may override wall flags; we cache them by name
        self._wall_by_name: dict[str, int] = {}

        # hierarchical structure graph
        self.structure_graph = build_structure_graph(self.objects)

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    def _get_wall_flag(self, p: Dict[str, Any]) -> int:
        name = p.get("name")
        if name in self._wall_by_name:
            return int(self._wall_by_name[name])
        return int(p.get("wall_flag", 0))

    def recalculate_globals(self, indiv: Individual) -> None:
        """
        Recomputes global geometry fields from rel_x/rel_y and hierarchy.
        """
        indiv_dict = {p["name"]: p for p in indiv}
        for comp in indiv:
            if comp.get("fixed"):
                continue

            parent = indiv_dict[comp["a_name"]]

            # effective container size in its own orientation
            a_w = parent["w"]
            a_d = parent["d"]
            a_w, a_d = (a_w, a_d) if (int(parent.get("orientation", 0)) % 180) == 0 else (a_d, a_w)

            # global center of parent
            a_x, a_y = parent["x"], parent["y"]
            a_preferred_side = parent.get("preferred_side", "top")

            # component orientation is relative + parent (mod 180)
            orientation = (int(comp.get("rel_o", 0)) + int(parent.get("orientation", 0))) % 180
            comp["orientation"] = orientation

            eff_w, eff_d = _effective_size_for_individual(comp)
            rel_x, rel_y = float(comp.get("rel_x", 0.0)), float(comp.get("rel_y", 0.0))

            # Global x,y from container coordinate system, based on parent's preferred_side
            if a_preferred_side == "top":
                x = a_x - a_w / 2 + rel_x
                y = a_y - a_d / 2 + rel_y
            elif a_preferred_side == "right":
                x = a_x + a_w / 2 - rel_y
                y = a_y - a_d / 2 + rel_x
            elif a_preferred_side == "bottom":
                x = a_x + a_w / 2 - rel_x
                y = a_y + a_d / 2 - rel_y
            elif a_preferred_side == "left":
                x = a_x - a_w / 2 + rel_y
                y = a_y + a_d / 2 - rel_x
            else:
                x = a_x - a_w / 2 + rel_x
                y = a_y - a_d / 2 + rel_y

            x_min = x - eff_w / 2.0
            y_min = y - eff_d / 2.0
            x_max = x + eff_w / 2.0
            y_max = y + eff_d / 2.0

            rel_preferred_side = preferred_container_side_for_component(
                (a_x - a_w / 2, a_y - a_d / 2, a_x + a_w / 2, a_y + a_d / 2),
                (x_min, y_min, x_max, y_max),
                comp.get("connection_side"),
            )
            preferred_side = rel_preferred_side

            comp["x"] = x
            comp["y"] = y
            comp["x_min"] = x_min
            comp["y_min"] = y_min
            comp["x_max"] = x_max
            comp["y_max"] = y_max
            comp["rel_preferred_side"] = rel_preferred_side
            comp["preferred_side"] = preferred_side

            rz = compute_reserved_zone(comp, (x_min, y_min, x_max, y_max), preferred_side)
            res_x_min, res_y_min, res_x_max, res_y_max = 0, 0, 0, 0
            if rz is not None:
                res_x_min, res_y_min, res_x_max, res_y_max = rz
            comp["res_x_min"] = res_x_min
            comp["res_y_min"] = res_y_min
            comp["res_x_max"] = res_x_max
            comp["res_y_max"] = res_y_max

    def _clip_rel_xy(self, *, rel_x: float, rel_y: float, a_w: float,
                     a_d: float, w_eff: float, d_eff: float, a_pside: str, ) -> Tuple[float, float]:
        """Clips rel_x/rel_y into valid container bounds. """
        if a_pside in ("top", "bottom"):
            rx_min, rx_max = w_eff / 2.0, a_w - w_eff / 2.0
            ry_min, ry_max = d_eff / 2.0, a_d - d_eff / 2.0
        else:
            # left/right: rel axes swapped
            rx_min, rx_max = d_eff / 2.0, a_d - d_eff / 2.0
            ry_min, ry_max = w_eff / 2.0, a_w - w_eff / 2.0

        rel_x = min(max(rel_x, rx_min), rx_max)
        rel_y = min(max(rel_y, ry_min), ry_max)
        return rel_x, rel_y

    # ---------------------------------------------------------------------
    # ES operators (new schema)
    # ---------------------------------------------------------------------
    def _recombine_intermediate(
        self,
        parents: List[Individual],
        parent_sigmas: List[List[Tuple[float, float]]],
    ) -> Tuple[Individual, List[Tuple[float, float]]]:
        """
        Intermediate recombination in *container coordinates*:
          - rel_x, rel_y averaged across parents (per component by index)
          - rel_o chosen from a random parent (discrete)
          - sigma averaged across parents
        We recompute derived globals after recombination.
        """
        if not parents:
            raise ValueError("_recombine_intermediate(): parents is empty")

        k = len(parents[0])
        base_parent = random.choice(parents)
        child: Individual = copy.deepcopy(base_parent)

        # average sigmas
        child_sigmas: List[Tuple[float, float]] = []
        for i in range(k):
            sx = sum(sig[i][0] for sig in parent_sigmas) / max(1, len(parent_sigmas))
            sy = sum(sig[i][1] for sig in parent_sigmas) / max(1, len(parent_sigmas))
            child_sigmas.append((sx, sy))

        # recombine rel_x/rel_y
        for i in range(k):
            if child[i].get("fixed"):
                continue
            rx = sum(float(p[i].get("rel_x", 0.0)) for p in parents) / len(parents)
            ry = sum(float(p[i].get("rel_y", 0.0)) for p in parents) / len(parents)
            child[i]["rel_x"] = rx
            child[i]["rel_y"] = ry

            # keep discrete rel_o from a random parent for diversity
            src = random.choice(parents)[i]
            if "rel_o" in src:
                child[i]["rel_o"] = int(src["rel_o"]) % 180

        self.recalculate_globals(child)
        return child, child_sigmas

    def _mutate_gaussian(
        self,
        indiv: Individual,
        sigmas: List[Tuple[float, float]],
        model_params: ModelParams,
    ) -> None:
        """
        Self-adaptive gaussian mutation on rel_x/rel_y (container coords), plus optional 90-degree rotation via rel_o.
        """
        indiv_dict = {p["name"]: p for p in indiv}

        # dimension count: 2 real params per non-fixed component
        n_vars = 0
        for p in indiv:
            if not p.get("fixed"):
                n_vars += 2
        n_vars = max(2, n_vars)

        if getattr(model_params, "self_adapt", False):
            tau0 = float(getattr(model_params, "tau0", 0.0) or (1.0 / math.sqrt(2.0 * n_vars)))
            tau = float(getattr(model_params, "tau", 0.0) or (1.0 / math.sqrt(2.0 * math.sqrt(n_vars))))
            N0 = random.gauss(0.0, 1.0)
        else:
            tau0 = tau = 0.0
            N0 = 0.0

        for i, p in enumerate(indiv):
            if p.get("fixed"):
                continue

            parent = indiv_dict[p["a_name"]]
            a_w = parent["w"]
            a_d = parent["d"]
            a_w, a_d = (a_w, a_d) if (int(parent.get("orientation", 0)) % 180) == 0 else (a_d, a_w)
            a_pside = parent.get("preferred_side", "top")

            # current effective size
            w_eff, d_eff = _effective_size_for_individual(p)

            sx, sy = sigmas[i]
            if getattr(model_params, "self_adapt", False):
                Ni_x = random.gauss(0.0, 1.0)
                Ni_y = random.gauss(0.0, 1.0)
                sx = max(1e-6, sx * math.exp(tau0 * N0 + tau * Ni_x))
                sy = max(1e-6, sy * math.exp(tau0 * N0 + tau * Ni_y))
                sigmas[i] = (sx, sy)

            # orientation mutation (90deg) if fits
            if random.random() < float(getattr(model_params, "orient_mut_prob", 0.0)):
                # try rotation only if swapped dims fit inside container
                if (d_eff <= a_w) and (w_eff <= a_d):
                    p["rel_o"] = (int(p.get("rel_o", 0)) + 90) % 180
                    # derived orientation will be recomputed later
                    w_eff, d_eff = d_eff, w_eff

            wall_flag = self._get_wall_flag(p)

            if self.wallfit_enabled and wall_flag == 1:
                # wall-fit placement (same policy as GA/BEA)
                rel_x, rel_y = random_center_in_container(
                    a_w,
                    a_d,
                    w_eff,
                    d_eff,
                    wall_fit_enable=True,
                    wall_flag=1,
                    connection_side=p.get("connection_side"),
                    rng=random,
                    preferred_side=a_pside,
                )
            else:
                rel_x = float(p.get("rel_x", w_eff / 2.0)) + random.gauss(0.0, sx)
                rel_y = float(p.get("rel_y", d_eff / 2.0)) + random.gauss(0.0, sy)
                rel_x, rel_y = self._clip_rel_xy(
                    rel_x=rel_x, rel_y=rel_y, a_w=a_w, a_d=a_d, w_eff=w_eff, d_eff=d_eff, a_pside=a_pside
                )

            p["rel_x"] = rel_x
            p["rel_y"] = rel_y

        self.recalculate_globals(indiv)

    # ---------------------------------------------------------------------
    # Main entry
    # ---------------------------------------------------------------------
    def run(self, model_params: ModelParams):
        """ Returns: (best_individual, best_score, elapsed_seconds) """
        t0 = time.perf_counter()

        bests_for_save: list[tuple[Individual, tuple]] = []
        indiv_for_anal: list[Any] = []

        if getattr(model_params, "seed", None) is not None:
            random.seed(model_params.seed)

        population = copy.deepcopy(self.init_population or [])
        if not population:
            raise ValueError("ES_algorithm.run(): init_population is empty")

        # derive overlaps + wall overrides from any representative individual
        overlaps_mandatory, wall = create_relation_df(population[0])
        self._wall_by_name = dict(wall)

        # ensure globals consistent before first evaluation
        # for ind in population:
        #     self.recalculate_globals(ind)

        # init sigma per individual (per-component)
        init_sigma = float(getattr(model_params, "init_sigma", 0.1) or 0.1)

        def init_sigmas(ind: Individual) -> List[Tuple[float, float]]:
            return [(init_sigma, init_sigma) for _ in range(len(ind))]

        # evaluate initial population
        scored_pop = [(ind, self.fitness(ind, 0, overlaps_mandatory, wall)) for ind in population]
        scored_pop.sort(key=lambda t: t[1][0])  # minimize score
        mu = int(getattr(model_params, "mu", 10) or 10)
        mu = max(1, min(mu, len(scored_pop)))

        # parents: (indiv, score_tuple, sigmas)
        parents: List[Tuple[Individual, tuple, List[Tuple[float, float]]]] = []
        for i in range(mu):
            ind_i = copy.deepcopy(scored_pop[i][0])
            sig_i = init_sigmas(ind_i)
            score_i = scored_pop[i][1]
            parents.append((ind_i, score_i, sig_i))

        # global best
        best_ind = copy.deepcopy(parents[0][0])
        best_score = float(parents[0][1][0])
        last_best = best_score
        no_improve = 0

        if self.log_mode:
            for ind, score_tuple in scored_pop:
                indiv_for_anal.append((copy.deepcopy(ind), score_tuple))

        # save initial best (BEA-style)
        bests_for_save.append((copy.deepcopy(best_ind), parents[0][1]))

        # ES parameters
        generations = int(getattr(model_params, "generations", 1) or 1)
        lam = int(getattr(model_params, "lambda_children", 40) or 40)
        lam = max(1, lam)

        # selection strategy: (mu+lambda) by default unless overridden
        plus_selection = bool(getattr(model_params, "plus_selection", True))

        for gen_idx in range(1, generations + 1):
            # offspring generation
            offspring: List[Tuple[Individual, tuple, List[Tuple[float, float]]]] = []

            for _ in range(lam):
                ksel = random.randint(2, min(4, len(parents))) if len(parents) >= 2 else 1
                chosen = random.sample(parents, ksel) if len(parents) >= ksel else parents

                chosen_inds = [c[0] for c in chosen]
                chosen_sigs = [c[2] for c in chosen]

                child, child_sig = self._recombine_intermediate(chosen_inds, chosen_sigs)
                self._mutate_gaussian(child, child_sig, model_params)

                score_tuple = self.fitness(child, gen_idx, overlaps_mandatory, wall)
                offspring.append((child, score_tuple, child_sig))

            # selection pool
            pool = parents + offspring if plus_selection else offspring
            pool.sort(key=lambda t: t[1][0])  # minimize

            # take next parents
            parents = [(copy.deepcopy(ind), score_tuple, sig) for (ind, score_tuple, sig) in pool[:mu]]

            # generation best for logging
            gen_best_ind = copy.deepcopy(parents[0][0])
            gen_best_score_tuple = parents[0][1]
            bests_for_save.append((gen_best_ind, gen_best_score_tuple))

            # update global best
            if float(gen_best_score_tuple[0]) < best_score:
                best_score = float(gen_best_score_tuple[0])
                best_ind = copy.deepcopy(gen_best_ind)

            # full log
            if self.log_mode:
                # log parents + offspring evaluations (explicitly)
                for ind, st, _sig in offspring:
                    indiv_for_anal.append((copy.deepcopy(ind), st))
                for ind, st, _sig in parents:
                    indiv_for_anal.append((copy.deepcopy(ind), st))

            # early stopping
            if (self.fitness_count() > getattr(model_params, "fitness_budget", float("inf"))) or (best_score == 0):
                break
            #
            # if best_score < last_best - 1e-9:
            #     last_best = best_score
            #     no_improve = 0
            # else:
            #     no_improve += 1
            #     if no_improve >= int(getattr(model_params, "patience", 10) or 10):
            #         break

        dt = time.perf_counter() - t0

        # --- logging ---
        if self.log_mode:
            save_the_indiv("indiv", self.project_name, self.solution_name, model_params, indiv_for_anal,
                           "Genetic evolutionary algorithm", dt, self.init_population_file, self.fitness_count(),
                           self.overlap_enabled, self.wallfit_enabled, out_dir=self.results_dir, )
        save_the_indiv("bests", self.project_name, self.solution_name, model_params, bests_for_save,
                       "Genetic evolutionary algorithm", dt, self.init_population_file, self.fitness_count(),
                       self.overlap_enabled, self.wallfit_enabled, out_dir=self.results_dir, )

        return best_ind, best_score, dt