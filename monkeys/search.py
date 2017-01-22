"""Search functionality and objective function tooling."""

import sys
import copy
import random
import functools
import contextlib
import collections

import numpy

from monkeys.trees import get_tree_info, UnsatisfiableType, build_tree, crossover, mutate


def tournament_select(trees, scoring_fn, selection_size, requires_population=False, cov_parsimony=False, random_parsimony=True, random_parsimony_prob=0.33, score_callback=None):
    _scoring_fn = scoring_fn(trees) if requires_population else scoring_fn

    avg_size = 0
    sizes = {}
    
    if cov_parsimony or random_parsimony:
        sizes = {tree: get_tree_info(tree).num_nodes for tree in trees}
        avg_size = sum(sizes.itervalues()) / float(len(sizes))
    
    if random_parsimony:
        # Poli 2003:
        scores = collections.defaultdict(lambda: -sys.maxsize)
        scores.update({
            tree: _scoring_fn(tree)
            for tree in trees
            if sizes[tree] <= avg_size or random_parsimony_prob < random.random() 
        })
    else:
        scores = {tree: _scoring_fn(tree) for tree in trees}

    if cov_parsimony:
        # Poli & McPhee 2008:
        covariance_matrix = numpy.cov(numpy.array([(sizes[tree], scores[tree]) for tree in trees]).T)
        size_variance = numpy.var([sizes[tree] for tree in trees])
        c = -(covariance_matrix / size_variance)[0, 1]  # 0, 1 should be correlation... is this the wrong way around?
        scores = {tree: score - c * sizes[tree] for tree, score in scores.iteritems()}

    # pseudo-pareto:
    non_neg_inf_scores = [s for s in scores.itervalues() if s != -sys.maxsize]
    try:
        avg_score = sum(non_neg_inf_scores) / float(len(non_neg_inf_scores))
    except ZeroDivisionError:
        avg_score = -sys.maxsize
    scores = {
        tree: -sys.maxsize if score < avg_score and sizes.get(tree, 0) > avg_size else score
        for tree, score in scores.iteritems() 
    }
    if callable(score_callback):
        score_callback(scores)
    all_failed = all(score == -sys.maxsize for score in scores.values())

    while True:
        tree = max(random.sample(trees, selection_size), key=scores.get)
        if scores[tree] == -sys.maxsize:
            try:
                new_tree = build_tree_to_requirements(scoring_fn)
            except UnsatisfiableType:
                continue
        else:
            try:
                with recursion_limit(1500):
                    new_tree = copy.deepcopy(tree)
            except RuntimeException:
                try:
                    new_tree = build_tree_to_requirements(scoring_fn)
                except UnsatisfiableType:
                    continue
        yield new_tree
        
        
def pre_evaluate(scoring_fn):
    @functools.wraps(scoring_fn)
    def wrapper(tree):
        try:
            evaluated_tree = tree.evaluate()
        except Exception:
            return -sys.maxsize
        return scoring_fn(evaluated_tree)
    return wrapper


def minimize(scoring_fn):
    @functools.wraps(scoring_fn)
    def wrapper(tree):
        return -scoring_fn(tree)
    return wrapper


def next_generation(trees, scoring_fn, select_fn=functools.partial(tournament_select, selection_size=25), crossover_rate=0.80, mutation_rate=0.01, score_callback=None):
    selector = select_fn(trees, scoring_fn, score_callback=score_callback)
    pop_size = len(trees)
    
    new_pop = [max(trees, key=scoring_fn)]
    for __ in xrange(pop_size - 1):
        if random.random() <= crossover_rate:
            for __ in xrange(99999):
                try:
                    new_pop.append(crossover(next(selector), next(selector)))
                    break
                except (UnsatisfiableType, RuntimeError):
                    continue
            else:
                new_pop.append(build_tree_to_requirements(scoring_fn))

        elif random.random() <= mutation_rate / (1 - crossover_rate):
            new_pop.append(mutate(next(selector)))

        else:
            new_pop.append(next(selector))

    return new_pop


def require(*inputs):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(tree):
            if not all(i in tree for i in inputs):
                return -sys.maxsize
            return fn(tree)
        wrapper.required_inputs = inputs
        return wrapper
    return decorator


@contextlib.contextmanager
def recursion_limit(limit):
    orig_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(limit)
    try:
        yield
    finally:
        sys.setrecursionlimit(orig_limit)
                
                
def build_tree_to_requirements(scoring_function):
    params = getattr(scoring_function, '__params', ())
    if len(params) != 1:
        raise ValueError("Scoring function must accept a single parameter.")
    return_type, = params
    
    for __ in xrange(9999):
        with recursion_limit(500):
            tree = build_tree(return_type, convert=False)
        requirements = getattr(scoring_function, 'required_inputs', ())
        if not all(req in tree for req in requirements):
            continue
        return tree
    
    raise UnsatisfiableType("Could not meet input requirements.")
    

def optimize(scoring_function, population_size=250, iterations=25, build_tree=build_tree, next_generation=next_generation, show_scores=True):  
    print "Creating initial population of {}.".format(population_size)
    sys.stdout.flush()
    
    population = []
    for __ in xrange(population_size):
        try:
            tree = build_tree_to_requirements(scoring_function)
            population.append(tree)
        except UnsatisfiableType:
            raise UnsatisfiableType(
                "Could not meet input requirements. Found only {} satisfying trees.".format(
                    len(population)
                )
            )
    best_tree = [random.choice(population)]
    
    def score_callback(iteration, scores):
        if not show_scores:
            return
        
        non_failure_scores = [
            score 
            for score in 
            scores.values()
            if score != -sys.maxsize
        ]
        try:
            average_score = sum(non_failure_scores) / len(non_failure_scores)
        except ZeroDivisionError:
            average_score = -sys.maxsize
        best_score = max(scores.values())
        
        best_tree.append(max(scores, key=scores.get))
        
        print "Iteration {}:\tBest: {:.2f}\tAverage: {:.2f}".format(
            iteration + 1,
            best_score,
            average_score,
        )
        sys.stdout.flush()
    
    print "Optimizing..."
    with recursion_limit(600):
        for iteration in xrange(iterations):
            callback = functools.partial(score_callback, iteration)
            population = next_generation(population, scoring_function, score_callback=callback)
        
    best_tree = max(best_tree, key=scoring_function)
    return best_tree
    
        