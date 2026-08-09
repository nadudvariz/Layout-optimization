from __future__ import annotations
from typing import List, Dict, Any, Tuple
import random, time, copy
from schemas.heuristic_schema import HEURISTICS_REGISTRY
from models import ModelParams, Room
from util.io_evolution import save_the_indiv
from algorithms.algorithms_common import (
    create_relation_df,
    build_structure_graph,
    random_individual,
    _effective_size_for_individual,
    random_center_in_container,
    preferred_container_side_for_component,
    compute_reserved_zone,
)

Individual = List[Dict[str, Any]]

class differential_algorithm:
    """
    Differential Evolution (DE)
    - Genes: rel_x, rel_y, rel_o (discrete 0/90)
    - Derived: x,y,x_min..,res_*,preferred_side,orientation
    - Logging: indiv + bests
    """
    def __init__(
        self,
        objects: List[Dict[str, Any]],
        room: Room,
        project_name: str,
        solution_name: str,
        heuristics: List[Dict[str, Any]] | None = None,
        constraints: List[Dict[str, Any]] | None = None,
        init_population: List[Individual] | None = None,
        init_population_file: str | None = None,
        fitness=None,
        overlap_enabled: bool = False,
        wallfit_enabled: bool = False,
        log_mode: bool = False,
        results_dir: str | None = None,
    ):
        self.objects = objects
        self.room = room
        self.project_name = project_name
        self.solution_name = solution_name
        self.heuristics = heuristics or HEURISTICS_REGISTRY
        self.constraints = constraints
        self.init_population = init_population
        self.init_population_file = init_population_file

        self.fitness = fitness.calculate_weight_sum
        self.fitness_count = fitness.get_usages

        self.overlap_enabled = overlap_enabled
        self.wallfit_enabled = wallfit_enabled
        self.log_mode = log_mode
        self.results_dir = results_dir

        self._wall_by_name: dict[str, int] = {}

        # overlap/hierarchia graph
        self.structure_graph = build_structure_graph(self.objects)

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    def _get_wall_flag(self, p: Dict[str, Any]) -> int:
        name = p.get("name")
        if name in self._wall_by_name:
            return int(self._wall_by_name[name])
        return int(p.get("wall_flag", 0))

    @staticmethod
    def _choose_3_distinct(n: int, exclude: int) -> Tuple[int, int, int]:
        if n < 4:
            raise ValueError("DE requires at least 4 individuals in the population.")
        idxs = list(range(n))
        idxs.pop(exclude)
        r1 = random.choice(idxs)
        idxs.remove(r1)
        r2 = random.choice(idxs)
        idxs.remove(r2)
        r3 = random.choice(idxs)
        return r1, r2, r3

    @staticmethod
    def _effective_size_from_dims(w: float, d: float, orientation_deg: int) -> Tuple[float, float]:
        if (orientation_deg % 180) == 0:
            return w, d
        return d, w

    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        if lo > hi:
            return (lo + hi) / 2.0
        return max(lo, min(hi, v))

    def _clamp_rel_xy(self, rel_x: float, rel_y: float, a_w: float,
                        a_d: float, a_pside: str, w_eff: float, d_eff: float,) -> Tuple[float, float]:
        """
        rel_x/rel_y clipping inside the container
        - top/bottom: rel_x is the width axis, rel_y is the depth axis
        - left/right: rel axes are swapped
        """
        if a_pside in ("top", "bottom"):
            rx_min, rx_max = w_eff / 2.0, a_w - w_eff / 2.0
            ry_min, ry_max = d_eff / 2.0, a_d - d_eff / 2.0
        else:
            rx_min, rx_max = d_eff / 2.0, a_d - d_eff / 2.0
            ry_min, ry_max = w_eff / 2.0, a_w - w_eff / 2.0

        rel_x = self._clamp(rel_x, rx_min, rx_max)
        rel_y = self._clamp(rel_y, ry_min, ry_max)
        return rel_x, rel_y

    def _maybe_rotate_rel_o_if_fits(self, comp: Dict[str, Any], parent: Dict[str, Any],
                                    a_w: float, a_d: float, a_pside: str, orient_mut_prob: float,) -> None:
        """
        Discrete orientation flip (rel_o += 90), only if it fits in the container.
        Same principle as in BEA/GA: 90° is okay if it fits after swapping.
        """
        if random.random() >= orient_mut_prob:
            return

        rel_o = int(comp.get("rel_o", 0)) % 180
        parent_ori = int(parent.get("orientation", 0)) % 180
        glob_ori = (rel_o + parent_ori) % 180

        w = float(comp.get("w", 0.0))
        d = float(comp.get("d", 0.0))
        w_eff, d_eff = self._effective_size_from_dims(w, d, glob_ori)

        # Change after 90°
        new_w_eff, new_d_eff = d_eff, w_eff

        # Will it fit?
        if new_w_eff > a_w + 1e-9 or new_d_eff > a_d + 1e-9:
            return

        # flip
        comp["rel_o"] = (rel_o + 90) % 180

        # rel_x/rel_y clamp according to the new size
        rel_x = float(comp.get("rel_x", new_w_eff / 2.0))
        rel_y = float(comp.get("rel_y", new_d_eff / 2.0))
        rel_x, rel_y = self._clamp_rel_xy(rel_x, rel_y, a_w, a_d, a_pside, new_w_eff, new_d_eff)
        comp["rel_x"] = rel_x
        comp["rel_y"] = rel_y

    # ---------------------------------------------------------------------
    # Recompute derived geometry
    # ---------------------------------------------------------------------
    def recalculate_globals(self, indiv: Individual) -> None:
        """
        Recalculates based on rel_x/rel_y/rel_o + hierarchy:
        x,y,x_min..,res_*,preferred_side,orientation,rel_preferred_side.
        """
        indiv_dict = {p["name"]: p for p in indiv}
        for comp in indiv:
            if comp.get("fixed"):
                continue

            parent = indiv_dict[comp["a_name"]]

            # container effective size (in its own orientation)
            a_w = float(parent["w"])
            a_d = float(parent["d"])
            if (int(parent.get("orientation", 0)) % 180) != 0:
                a_w, a_d = a_d, a_w

            # parent global center
            a_x, a_y = float(parent["x"]), float(parent["y"])
            a_preferred_side = parent.get("preferred_side", "top")

            # component global orientation: rel_o + parent
            orientation = (int(comp.get("rel_o", 0)) + int(parent.get("orientation", 0))) % 180
            comp["orientation"] = orientation

            # effective (oriented) size
            eff_w, eff_d = _effective_size_for_individual(comp)

            rel_x, rel_y = float(comp.get("rel_x", 0.0)), float(comp.get("rel_y", 0.0))

            # global x,y from the container's relative coordinate system
            if a_preferred_side == "top":
                x = a_x - a_w / 2.0 + rel_x
                y = a_y - a_d / 2.0 + rel_y
            elif a_preferred_side == "right":
                x = a_x + a_w / 2.0 - rel_y
                y = a_y - a_d / 2.0 + rel_x
            elif a_preferred_side == "bottom":
                x = a_x + a_w / 2.0 - rel_x
                y = a_y + a_d / 2.0 - rel_y
            elif a_preferred_side == "left":
                x = a_x - a_w / 2.0 + rel_y
                y = a_y + a_d / 2.0 - rel_x
            else:
                x = a_x - a_w / 2.0 + rel_x
                y = a_y - a_d / 2.0 + rel_y

            x_min = x - eff_w / 2.0
            y_min = y - eff_d / 2.0
            x_max = x + eff_w / 2.0
            y_max = y + eff_d / 2.0

            rel_preferred_side = preferred_container_side_for_component(
                (a_x - a_w / 2.0, a_y - a_d / 2.0, a_x + a_w / 2.0, a_y + a_d / 2.0),
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
            res_x_min, res_y_min, res_x_max, res_y_max = 0.0, 0.0, 0.0, 0.0
            if rz is not None:
                res_x_min, res_y_min, res_x_max, res_y_max = rz
            comp["res_x_min"] = res_x_min
            comp["res_y_min"] = res_y_min
            comp["res_x_max"] = res_x_max
            comp["res_y_max"] = res_y_max

    # ---------------------------------------------------------------------
    # Trial construction
    # ---------------------------------------------------------------------
    def _build_trial(
        self,
        target: Individual,
        base: Individual,
        add1: Individual,
        add2: Individual,
        F: float,
        CR: float,
        orient_mut_prob: float,
    ) -> Individual:
        """
        Donor = base + F*(add1-add2) on (rel_x, rel_y) continuous genes.
        rel_o discrete: donor/target selection with binomial crossover.
        """
        trial = copy.deepcopy(target)

        tmap = {p["name"]: p for p in target}
        bmap = {p["name"]: p for p in base}
        a1map = {p["name"]: p for p in add1}
        a2map = {p["name"]: p for p in add2}

        # only the loci of non-fixed components are counted
        gene_sites: List[Tuple[str, str]] = []
        for p in target:
            if p.get("fixed"):
                continue
            nm = p["name"]
            gene_sites.extend([(nm, "rel_x"), (nm, "rel_y"), (nm, "rel_o")])

        if not gene_sites:
            return trial

        jrand = random.randrange(len(gene_sites))

        for gi, (nm, key) in enumerate(gene_sites):
            use_donor = (random.random() < CR) or (gi == jrand)

            tp = tmap[nm]
            if tp.get("fixed"):
                continue

            bp = bmap.get(nm, tp)
            p1 = a1map.get(nm, tp)
            p2 = a2map.get(nm, tp)

            # trial component reference
            outp = next(p for p in trial if p["name"] == nm)

            if not use_donor:
                continue

            if key == "rel_x":
                outp["rel_x"] = float(bp.get("rel_x", 0.0)) + F * (
                    float(p1.get("rel_x", 0.0)) - float(p2.get("rel_x", 0.0))
                )
            elif key == "rel_y":
                outp["rel_y"] = float(bp.get("rel_y", 0.0)) + F * (
                    float(p1.get("rel_y", 0.0)) - float(p2.get("rel_y", 0.0))
                )
            elif key == "rel_o":
                outp["rel_o"] = int(bp.get("rel_o", tp.get("rel_o", 0))) % 180

        # clamp + wallfit handling by components
        indiv_dict = {p["name"]: p for p in trial}
        for comp in trial:
            if comp.get("fixed"):
                continue

            parent = indiv_dict[comp["a_name"]]
            a_w = float(parent["w"])
            a_d = float(parent["d"])
            if (int(parent.get("orientation", 0)) % 180) != 0:
                a_w, a_d = a_d, a_w
            a_pside = parent.get("preferred_side", "top")

            # effective size based on rel_o (with parent orientation)
            rel_o = int(comp.get("rel_o", 0)) % 180
            glob_ori = (rel_o + int(parent.get("orientation", 0))) % 180
            w = float(comp.get("w", 0.0))
            d = float(comp.get("d", 0.0))
            w_eff, d_eff = self._effective_size_from_dims(w, d, glob_ori)

            # wallfit: if it must fit against a wall, generate a wall-compatible rel position
            wall_flag = self._get_wall_flag(comp)
            if self.wallfit_enabled and wall_flag == 1:
                rx, ry = random_center_in_container(
                    a_w,
                    a_d,
                    w_eff,
                    d_eff,
                    wall_fit_enable=True,
                    wall_flag=1,
                    connection_side=comp.get("connection_side"),
                    rng=random,
                    preferred_side=a_pside,
                )
                comp["rel_x"], comp["rel_y"] = rx, ry
            else:
                # clamp inside the container
                rel_x = float(comp.get("rel_x", w_eff / 2.0))
                rel_y = float(comp.get("rel_y", d_eff / 2.0))
                rel_x, rel_y = self._clamp_rel_xy(rel_x, rel_y, a_w, a_d, a_pside, w_eff, d_eff)
                comp["rel_x"], comp["rel_y"] = rel_x, rel_y

            # optional orientation flip mutation (only if it fits)
            self._maybe_rotate_rel_o_if_fits(comp, parent, a_w, a_d, a_pside, orient_mut_prob)

        # Recalculate derived fields
        self.recalculate_globals(trial)
        return trial

    # ---------------------------------------------------------------------
    # Main entry
    # ---------------------------------------------------------------------
    def run(self, model_params: ModelParams, strategy: str = "rand1bin"):
        """
        Runs DE and returns (best_individual, best_score, elapsed_seconds).
        strategy: "rand1bin" | "best1bin"
        """
        t0 = time.perf_counter()
        bests_for_save: list[tuple[Individual, tuple]] = []
        indiv_for_anal: list[Any] = []

        assert strategy in ("rand1bin", "best1bin")

        if getattr(model_params, "seed", None) is not None:
            random.seed(model_params.seed)

        generations = int(getattr(model_params, "generations", 50))
        pop_size_param = int(getattr(model_params, "population_size", 20))
        fitness_budget = int(getattr(model_params, "fitness_budget", 1_000_000))
        patience = int(getattr(model_params, "patience", generations + 1))

        F = float(getattr(model_params, "F", 0.5))
        CR = float(getattr(model_params, "CR", 0.9))
        orient_mut_prob = float(getattr(model_params, "orient_mut_prob", 0.05))

        # population init
        population = copy.deepcopy(self.init_population or [])
        if not population:
            population = [
                random_individual(
                    self.objects,
                    self.room,
                    overlap_enabled=self.overlap_enabled,
                    wallfit_enabled=self.wallfit_enabled,
                )
                for _ in range(pop_size_param)
            ]

        pop_size = len(population)
        if pop_size < 4:
            raise ValueError("differential_algorithm.run(): population size must be >= 4")

        overlaps_mandatory, wall = create_relation_df(population[0])
        self._wall_by_name = dict(wall)

        # initial evaluation
        scores = [self.fitness(ind, 0, overlaps_mandatory, wall) for ind in population]
        best_idx = min(range(pop_size), key=lambda i: scores[i][0])
        best_ind = copy.deepcopy(population[best_idx])
        best_score = scores[best_idx][0]

        last_best = best_score
        no_improve = 0

        if self.log_mode:
            for i in range(pop_size):
                indiv_for_anal.append((copy.deepcopy(population[i]), scores[i]))
        bests_for_save.append((copy.deepcopy(best_ind), scores[best_idx]))

        # generations
        for gen_idx in range(1, generations + 1):
            # DE selection
            for i in range(pop_size):
                target = population[i]
                target_score = scores[i]

                if strategy == "rand1bin":
                    r1, r2, r3 = self._choose_3_distinct(pop_size, exclude=i)
                    base = population[r1]
                    add1 = population[r2]
                    add2 = population[r3]
                else:  # "best1bin"
                    # base = current best, plus 2 random distinct
                    base = best_ind
                    r2, r3, _dummy = self._choose_3_distinct(pop_size, exclude=i)
                    add1 = population[r2]
                    add2 = population[r3]

                trial = self._build_trial(
                    target=target,
                    base=base,
                    add1=add1,
                    add2=add2,
                    F=F,
                    CR=CR,
                    orient_mut_prob=orient_mut_prob,
                )

                trial_score = self.fitness(trial, gen_idx, overlaps_mandatory, wall)

                # minimization: smaller is better
                if trial_score[0] < target_score[0]:
                    population[i] = trial
                    scores[i] = trial_score

                    if trial_score[0] < best_score:
                        best_score = trial_score[0]
                        best_ind = copy.deepcopy(trial)

            # gen best + log
            gen_best_idx = min(range(pop_size), key=lambda j: scores[j][0])
            gen_best_ind = copy.deepcopy(population[gen_best_idx])
            gen_best_score_tuple = scores[gen_best_idx]
            bests_for_save.append((gen_best_ind, gen_best_score_tuple))

            if self.log_mode:
                for j in range(pop_size):
                    indiv_for_anal.append((copy.deepcopy(population[j]), scores[j]))

            # stopping conditions
            if (self.fitness_count() > fitness_budget) or (best_score == 0):
                break
            #
            # if best_score < last_best - 1e-9:
            #     last_best = best_score
            #     no_improve = 0
            # else:
            #     no_improve += 1
            #     if no_improve >= patience:
            #         break

        dt = time.perf_counter() - t0

        if self.log_mode:
            save_the_indiv(
                "indiv",
                self.project_name,
                self.solution_name,
                model_params,
                indiv_for_anal,
                "Differential evolutionary algorithm",
                dt,
                self.init_population_file,
                self.fitness_count(),
                self.overlap_enabled,
                self.wallfit_enabled,
                out_dir=self.results_dir,
            )

        save_the_indiv(
            "bests",
            self.project_name,
            self.solution_name,
            model_params,
            bests_for_save,
            "Differential evolutionary algorithm",
            dt,
            self.init_population_file,
            self.fitness_count(),
            self.overlap_enabled,
            self.wallfit_enabled,
            out_dir=self.results_dir,
        )

        return best_ind, best_score, dt