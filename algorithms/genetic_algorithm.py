from __future__ import annotations
from typing import List, Dict, Any
import networkx as nx
from schemas.heuristic_schema import HEURISTICS_REGISTRY
from models import ModelParams, Room
from util.io_evolution import save_the_indiv
import time, random, copy
from algorithms.algorithms_common import (create_relation_df, build_structure_graph, _effective_size_for_individual,
     random_center_in_container, preferred_container_side_for_component, compute_reserved_zone, directions)

Individual = List[Dict]

class genetic_algorithm():
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
        self.fitness = fitness.calculate_weight_sum
        self.fitness_count = fitness.get_usages
        self.log_mode = log_mode
        self.overlap_enabled = overlap_enabled
        self.wallfit_enabled = wallfit_enabled
        self._wall_by_name: dict[str, int] = {}
        self.results_dir = results_dir

    def _tournament(self, scored, k=3, minimize = False):
        cand = random.sample(scored, k=min(k, len(scored)))
        return min(cand, key=lambda x: x[1])[0] if minimize else max(cand, key=lambda x: x[1])[0]

    def _crossover(self, a, b, crossover_prob):
        idx_b = {p["name"]: p for p in b}
        child = []
        for pa in a:
            pb = idx_b.get(pa["name"], pa)
            src = pa if random.random() < crossover_prob else pb
            child.append(dict(src))

        return child

    def _mutate(self, indiv, model_params, rng):
        loc_p = model_params.loc_mut_prob
        orient_p = model_params.orient_mut_prob
        indiv_dict = {p["name"]: p for p in indiv}
        G = build_structure_graph(indiv)

        for p in indiv:
            if p["fixed"]: continue
            acc = indiv_dict.get(p["a_name"])

            #Initialization
            changed = False
            debug = ""
            # data of ancestor
            a_w, a_d = acc["x_max"] - acc["x_min"], acc["y_max"] - acc["y_min"]
            a_x, a_y = acc.get("x"), acc.get("y")
            a_pside = acc.get("preferred_side")
            # data of component
            w_eff, d_eff = _effective_size_for_individual(p)
            new_x_rel, new_y_rel = p.get("rel_x"), p.get("rel_y")
            ori = p["orientation"]
            rel_o = p["rel_o"]

            # --- orientation mutation ---
            if rng.random() < orient_p:
                # only if it fits
                rotatatble = (d_eff <= a_w) and (w_eff <= a_d)
                if rotatatble:
                    ori = (ori + 90) % 180
                    rel_o = (rel_o + 90) % 180
                    w_eff, d_eff = d_eff, w_eff

                    if a_pside in ("top", "bottom"):
                        rx_min, rx_max = w_eff / 2, a_w - w_eff / 2
                        ry_min, ry_max = d_eff / 2, a_d - d_eff / 2
                    else:  # "right" or "left" – here the rel axes are swapped
                        rx_min, rx_max = d_eff / 2, a_d - d_eff / 2  # rel_x is the global 'longitude' direction
                        ry_min, ry_max = w_eff / 2, a_w - w_eff / 2  # rel_y is the global 'latitude' direction

                    new_x_rel = min(max(new_x_rel, rx_min), rx_max)
                    new_y_rel = min(max(new_y_rel, ry_min), ry_max)

                    debug += " rot"
                    changed = True

            # --- location mutation ---
            if rng.random() < loc_p:
                # only a place that is inside
                wall_flag = self._get_wall_flag(p)
                debug += " loc"
                changed = True

                if self.wallfit_enabled and wall_flag == 1:
                    # Mutation between wall-fitting components

                    new_x_rel, new_y_rel = random_center_in_container(
                        a_w, a_d, w_eff, d_eff,
                        wall_fit_enable=True,
                        wall_flag=1,
                        connection_side=p.get("connection_side"),
                        rng=rng,
                        preferred_side=a_pside,
                    )
                else:
                    # Freely moving components: small steps inside the container
                    step_x = rng.uniform(-0.2 * a_w, 0.2 * a_w)
                    step_y = rng.uniform(-0.2 * a_d, 0.2 * a_d)

                    if a_pside in ("top", "bottom"):
                        rx_min, rx_max = w_eff / 2, a_w - w_eff / 2
                        ry_min, ry_max = d_eff / 2, a_d - d_eff / 2
                    else:  # "right" or "left" – here the rel axes are swapped
                        rx_min, rx_max = d_eff / 2, a_d - d_eff / 2  # rel_x is the global 'longitude' direction
                        ry_min, ry_max = w_eff / 2, a_w - w_eff / 2  # rel_y is the global 'latitude' direction

                    new_x_rel = min(max(new_x_rel + step_x, rx_min), rx_max)
                    new_y_rel = min(max(new_y_rel + step_y, ry_min), ry_max)

            if changed:
                # Globalási x, y meghatározása
                if a_pside == "top":
                    x = a_x - a_w / 2 + new_x_rel
                    y = a_y - a_d / 2 + new_y_rel
                elif a_pside == "right":
                    x = a_x + a_w / 2 - new_y_rel
                    y = a_y - a_d / 2 + new_x_rel
                elif a_pside == "bottom":
                    x = a_x + a_w / 2 - new_x_rel
                    y = a_y + a_d / 2 - new_y_rel
                elif a_pside == "left":
                    x = a_x - a_w / 2 + new_y_rel
                    y = a_y + a_d / 2 - new_x_rel

                x_min = x - w_eff / 2.0
                y_min = y - d_eff / 2.0
                x_max = x + w_eff / 2.0
                y_max = y + d_eff / 2.0

                rel_preferred_side = preferred_container_side_for_component((a_x - a_w/2, a_y - a_d/2, a_x + a_w/2, a_y + a_d/2),
                                                                (x_min, y_min, x_max, y_max) , p.get("connection_side"))

                preferred_side = rel_preferred_side

                res_x_min, res_y_min, res_x_max, res_y_max = 0, 0, 0, 0
                rz = compute_reserved_zone(p, (x_min, y_min, x_max, y_max), preferred_side)
                if rz is not None:
                    res_x_min, res_y_min, res_x_max, res_y_max = rz

                p["rel_x"] = round(new_x_rel,4)
                p["rel_y"]=  round(new_y_rel,4)
                p["rel_o"] = rel_o
                p["rel_preferred_side"] = rel_preferred_side
                # container global coordinates
                p["x"] = round(x, 4)
                p["y"] = round(y, 4)
                p["orientation"] = ori
                p["x_min"] = round(x_min,4)
                p["y_min"] = round(y_min,4)
                p["x_max"] = round(x_max,4)
                p["y_max"] = round(y_max,4)
                p["preferred_side"] = preferred_side
                p["res_x_min"] = round(res_x_min,4)
                p["res_y_min"] = round(res_y_min,4)
                p["res_x_max"] = round(res_x_max,4)
                p["res_y_max"] = round(res_y_max,4)
                p["debug"] = debug

                # if overlap_enabled, children should be adjusted accordingly
                if self.overlap_enabled:# and changed
                    if p["name"] in G:
                        for node in nx.descendants(G, p["name"]):
                            comp = indiv_dict[node]
                            acc = indiv_dict[comp["a_name"]]
                            # data of ancestor
                            ga_w, ga_d = acc["x_max"] - acc["x_min"], acc["y_max"] - acc["y_min"]
                            ga_x, ga_y = acc["x"], acc["y"]
                            ga_pside = acc["preferred_side"]
                            ga_ori = acc["orientation"]

                            # current node data
                            grel_o = comp["rel_o"]
                            gori = (ga_ori + grel_o) % 180
                            gx_rel, gy_rel = comp.get("rel_x"), comp.get("rel_y")
                            gw_eff, gd_eff = (comp["w"], comp["d"]) if gori == 0 else (comp["d"], comp["w"])

                            # Global x, y calculation
                            if ga_pside == "top":
                                x = ga_x - ga_w / 2 + gx_rel
                                y = ga_y - ga_d / 2 + gy_rel
                            elif ga_pside == "right":
                                x = ga_x + ga_w / 2 - gy_rel
                                y = ga_y - ga_d / 2 + gx_rel
                            elif ga_pside == "bottom":
                                x = ga_x + ga_w / 2 - gx_rel
                                y = ga_y + ga_d / 2 - gy_rel
                            elif ga_pside == "left":
                                x = ga_x - ga_w / 2 + gy_rel
                                y = ga_y + ga_d / 2 - gx_rel
                            else:
                                pass

                            x_min = x - gw_eff / 2.0
                            y_min = y - gd_eff / 2.0
                            x_max = x + gw_eff / 2.0
                            y_max = y + gd_eff / 2.0

                            rel_preferred_side = preferred_container_side_for_component(
                                (ga_x - ga_w / 2, ga_y - ga_d / 2, ga_x + ga_w / 2, ga_y + ga_d / 2),
                                (x_min, y_min, x_max, y_max), comp.get("connection_side"))

                            preferred_side = rel_preferred_side

                            comp["rel_preferred_side"] = rel_preferred_side
                            comp["x"] = round(x,4)  # container global coordinate
                            comp["y"] = round(y,4)
                            comp["x_min"] = round(x_min,4)
                            comp["y_min"] = round(y_min,4)
                            comp["x_max"] = round(x_max,4)
                            comp["y_max"] = round(y_max,4)
                            comp["preferred_side"] = preferred_side
                            comp["orientation"] = gori

                            res_x_min, res_y_min, res_x_max, res_y_max = 0, 0, 0, 0
                            rz = compute_reserved_zone(comp, (x_min, y_min, x_max, y_max), preferred_side)
                            if rz is not None:
                                res_x_min, res_y_min, res_x_max, res_y_max = rz

                            comp["res_x_min"] = round(res_x_min, 4)
                            comp["res_y_min"] = round(res_y_min, 4)
                            comp["res_x_max"] = round(res_x_max, 4)
                            comp["res_y_max"] = round(res_y_max, 4)

    def _get_wall_flag(self, p):
        """
        Wall flag, with values ​​modified by create_relation_df.
        If no value is modified, the component's own wall_flag field will take precedence.
        """
        name = p.get("name")
        if name in self._wall_by_name:
            return self._wall_by_name[name]
        return int(p.get("wall_flag", 0))

    def recalculate_globals(self, indiv):
        indiv_dict = {p["name"]: p for p in indiv}
        for comp in indiv:
            if comp["fixed"]: continue

            orientation = (int(comp["rel_o"]) + int(indiv_dict[comp["a_name"]]["orientation"])) % 180
            eff_w, eff_d = (comp["w"], comp["d"]) if orientation == 0 else (comp["d"], comp["w"])

            # Global x, y calculation I.
            a_w = indiv_dict[comp["a_name"]]["w"]
            a_d = indiv_dict[comp["a_name"]]["d"]
            a_w, a_d = (a_w, a_d) if indiv_dict[comp["a_name"]]["orientation"] == 0 else (a_d, a_w)

            a_x, a_y = indiv_dict[comp["a_name"]]["x"], indiv_dict[comp["a_name"]]["y"]
            a_preferred_side = indiv_dict[comp["a_name"]]["preferred_side"]
            rel_x, rel_y = comp["rel_x"], comp["rel_y"]

            # Global x, y calculation II.
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

            x_min = x - eff_w / 2.0
            y_min = y - eff_d / 2.0
            x_max = x + eff_w / 2.0
            y_max = y + eff_d / 2.0

            rel_preferred_side = preferred_container_side_for_component(
                (a_x - a_w / 2, a_y - a_d / 2, a_x + a_w / 2, a_y + a_d / 2),
                (x_min, y_min, x_max, y_max), comp["connection_side"])
            preferred_side = rel_preferred_side

            comp["rel_preferred_side"] = rel_preferred_side
            comp["x"] = round(x, 4)
            comp["y"] = round(y, 4)
            comp["orientation"] = orientation
            comp["preferred_side"] = preferred_side
            comp["x_min"] = round(x_min, 4)
            comp["y_min"] = round(y_min, 4)
            comp["x_max"] = round(x_max, 4)
            comp["y_max"] = round(y_max, 4)

            rz = compute_reserved_zone(comp, (x_min, y_min, x_max, y_max), preferred_side)

            res_x_min, res_y_min, res_x_max, res_y_max = 0, 0, 0, 0
            if rz is not None:
                res_x_min, res_y_min, res_x_max, res_y_max = rz

            comp["res_x_min"] = round(res_x_min, 4)
            comp["res_y_min"] = round(res_y_min, 4)
            comp["res_x_max"] = round(res_x_max, 4)
            comp["res_y_max"] = round(res_y_max, 4)

    def run(self, model_params: ModelParams):

        def _evaluate_population(population: List[Individual], generation: int, overlaps_mandatory, wall):
            scored = [
                (ind, self.fitness(ind, generation, overlaps_mandatory, wall))
                for ind in population
            ]
            scored.sort(key=lambda x: x[1][0])

            if self.log_mode:
                for ind, score in scored:
                    indiv_for_anal.append((copy.deepcopy(ind), score))

            gen_best_ind = copy.deepcopy(scored[0][0])
            gen_best_score_tuple = scored[0][1]
            bests_for_save.append((gen_best_ind, gen_best_score_tuple))

            return scored, gen_best_ind, gen_best_score_tuple

        # 1) initialization
        t0 = time.perf_counter()
        bests_for_save = []
        indiv_for_anal = []
        best_ind = None
        best_score = float("inf")
        last_best = best_score
        no_improve = 0
        population = copy.deepcopy(self.init_population or [])
        overlaps_mandatory, wall = create_relation_df(population[0])
        self._wall_by_name = dict(wall)

        # initial population (generation 0) is also evaluated and logged
        scored, gen_best_ind, gen_best_score_tuple = _evaluate_population(population, 0, overlaps_mandatory, wall)
        if gen_best_score_tuple[0] < best_score:
            best_ind = copy.deepcopy(gen_best_ind)
            best_score = gen_best_score_tuple[0]

        # 2) genetic evolution
        for generation in range(1, int(model_params.generations) + 1):

            new_pop = [copy.deepcopy(ind) for ind, _ in scored[:model_params.elite]]

            while len(new_pop) < model_params.population_size:
                # crossover
                a = self._tournament(scored, k=model_params.tournament_size, minimize = True)
                b = self._tournament(scored, k=model_params.tournament_size, minimize = True)
                child = self._crossover(a, b, model_params.crossover_prob)
                self.recalculate_globals(child)
                # mutation
                if random.random() < model_params.selection_prob:
                    self._mutate(child, model_params, random)
                new_pop.append(child)
            population = new_pop

            scored, gen_best_ind, gen_best_score_tuple = _evaluate_population(
                population, generation, overlaps_mandatory, wall
            )

            if gen_best_score_tuple[0] < best_score:
                best_ind = copy.deepcopy(gen_best_ind)
                best_score = gen_best_score_tuple[0]

            # out of fitness budget or achieve the goal
            if (self.fitness_count() > model_params.fitness_budget) or (best_score == 0):
                break
            # if best_score < last_best - 1e-9:
            #     last_best = best_score
            #     no_improve = 0
            # else:
            #     no_improve += 1
            #     if no_improve >= model_params.patience:
            #         break

        dt = time.perf_counter() - t0
        if self.log_mode: # == "full log":
            save_the_indiv("indiv", self.project_name, self.solution_name, model_params, indiv_for_anal,
                            "Genetic evolutionary algorithm", dt, self.init_population_file, self.fitness_count(),
                           self.overlap_enabled, self.wallfit_enabled, out_dir=self.results_dir,)
        save_the_indiv("bests", self.project_name, self.solution_name, model_params, bests_for_save,
                       "Genetic evolutionary algorithm", dt, self.init_population_file, self.fitness_count(),
                       self.overlap_enabled, self.wallfit_enabled, out_dir=self.results_dir,)
        return best_ind, best_score, dt