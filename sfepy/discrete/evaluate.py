from __future__ import absolute_import
from copy import copy

import numpy as nm

from sfepy.base.base import output, get_default, OneTypeList, Struct, basestr
from sfepy.discrete import Equations, Variables, Region, Integral, Integrals
from sfepy.discrete.common.fields import setup_extra_data
import six

def apply_ebc_to_matrix(mtx, ebc_rows, epbc_rows=None):
    """
    Apply E(P)BC to matrix rows: put 1 to the diagonal for EBC DOFs, 1 to the
    diagonal for master EPBC DOFs, -1 to the [master, slave] entries. It is
    assumed, that the matrix contains zeros in EBC and master EPBC DOFs rows
    and columns.
    """
    data, prows, cols = mtx.data, mtx.indptr, mtx.indices
    # Does not change the sparsity pattern.
    for ir in ebc_rows:
        for ic in range(prows[ir], prows[ir + 1]):
            if (cols[ic] == ir):
                data[ic] = 1.0

    if epbc_rows is not None:
        master, slave = epbc_rows

        # Changes sparsity pattern in-place - allocates new entries! The master
        # DOFs are not allocated by Equations.create_matrix_graph(), see
        # create_adof_conns().
        mtx[master, master] = 1.0
        mtx[master, slave] = -1.0

##
# 02.10.2007, c
class Evaluator( Struct ):
    pass

##
# 02.10.2007, c
class BasicEvaluator( Evaluator ):

    def __init__(self, problem, matrix_hook=None):
        Evaluator.__init__(self, problem=problem,
                           matrix_hook=matrix_hook)

    def new_ulf_iteration(self, nls, vec, it, err, err0):

        pb = self.problem

        vec = self.make_full_vec(vec)
        pb.equations.set_variables_from_state(vec)

        upd_vars = pb.conf.options.get('mesh_update_variables', None)
        for varname in upd_vars:
            try:
                state = pb.equations.variables[varname]
            except IndexError:
                msg = 'variable "%s" does not exist!' % varname
                raise KeyError( msg )

        nods = state.field.get_dofs_in_region(state.field.region, merge=True)
        coors = pb.domain.get_mesh_coors().copy()
        vs = state()
        coors[nods,:] = coors[nods,:] + vs.reshape(len(nods), state.n_components)
        if pb.ts.step == 1 and it == 0:
            state.field.save_mappings()

        state.field.clear_mappings()
        pb.set_mesh_coors(coors, update_fields=False, actual=True,
                          clear_all=False)

    def eval_residual( self, vec, is_full = False ):
        if not is_full and self.problem.active_only:
            vec = self.make_full_vec( vec )

        vec_r = self.problem.equations.eval_residuals(vec)
        if self.matrix_hook is not None:
            vec_r = self.matrix_hook(vec_r, self.problem, call_mode='residual')

        return vec_r

    def eval_tangent_matrix( self, vec, mtx = None, is_full = False ):
        if isinstance(vec, basestr) and vec == 'linear':
            return get_default(mtx, self.problem.mtx_a)

        if not is_full and self.problem.active_only:
            vec = self.make_full_vec( vec )

        pb = self.problem
        if mtx is None:
            mtx = pb.mtx_a
        mtx = pb.equations.eval_tangent_matrices(vec, mtx)

        if not pb.active_only:
            apply_ebc_to_matrix(mtx, *pb.get_ebc_indices())

        if self.matrix_hook is not None:
            mtx = self.matrix_hook(mtx, pb, call_mode='basic')

        return mtx

    def make_full_vec( self, vec ):
        return self.problem.equations.make_full_vec(vec)

##
# 04.10.2007, c
class LCBCEvaluator( BasicEvaluator ):

    ##
    # 04.10.2007, c
    def __init__(self, problem, matrix_hook=None):
        BasicEvaluator.__init__(self, problem, matrix_hook=matrix_hook)
        self.mtx_lcbc = problem.equations.get_lcbc_operator()

    ##
    # 04.10.2007, c
    def eval_residual( self, vec, is_full = False ):
        if not is_full:
            vec = self.make_full_vec( vec )
        vec_r = BasicEvaluator.eval_residual( self, vec, is_full = True )
        vec_rr = self.mtx_lcbc.T * vec_r
        if self.matrix_hook is not None:
            vec_rr = self.matrix_hook(vec_rr, self.problem,
                                      call_mode='lcbc_residual')
        return vec_rr

    ##
    # 04.10.2007, c
    def eval_tangent_matrix( self, vec, mtx = None, is_full = False ):
        if isinstance(vec, basestr) and vec == 'linear':
            return get_default(mtx, self.problem.mtx_a)

        if not is_full:
            vec = self.make_full_vec( vec )
        mtx = BasicEvaluator.eval_tangent_matrix( self, vec, mtx = mtx,
                                                  is_full = True )
        mtx_r = self.mtx_lcbc.T * mtx * self.mtx_lcbc
        mtx_r = mtx_r.tocsr()
        mtx_r.sort_indices()
##         import pylab
##         from sfepy.base.plotutils import spy
##         spy( mtx_r )
##         pylab.show()
##         print mtx_r.__repr__()

        if self.matrix_hook is not None:
            mtx_r = self.matrix_hook(mtx_r, self.problem, call_mode='lcbc')

        return mtx_r

def create_evaluable(expression, fields, materials, variables, integrals,
                     regions=None,
                     ebcs=None, epbcs=None, lcbcs=None,
                     ts=None, functions=None,
                     auto_init=False, mode='eval', extra_args=None,
                     active_only=True, verbose=True, kwargs=None):
    """
    Create evaluable object (equations and corresponding variables)
    from the `expression` string.

    Parameters
    ----------
    expression : str
        The expression to evaluate.
    fields : dict
        The dictionary of fields used in `variables`.
    materials : Materials instance
        The materials used in the expression.
    variables : Variables instance
        The variables used in the expression.
    integrals : Integrals instance
        The integrals to be used.
    regions : Region instance or list of Region instances
        The region(s) to be used. If not given, the regions defined
        within the fields domain are used.
    ebcs : Conditions instance, optional
        The essential (Dirichlet) boundary conditions for 'weak'
        mode.
    epbcs : Conditions instance, optional
        The periodic boundary conditions for 'weak'
        mode.
    lcbcs : Conditions instance, optional
        The linear combination boundary conditions for 'weak'
        mode.
    ts : TimeStepper instance, optional
        The time stepper.
    functions : Functions instance, optional
        The user functions for boundary conditions, materials
        etc.
    auto_init : bool
        Set values of all variables to all zeros.
    mode : one of 'eval', 'el_avg', 'qp', 'weak'
        The evaluation mode - 'weak' means the finite element
        assembling, 'qp' requests the values in quadrature points,
        'el_avg' element averages and 'eval' means integration over
        each term region.
    extra_args : dict, optional
        Extra arguments to be passed to terms in the expression.
    active_only : bool
        If True, in 'weak' mode, the (tangent) matrices and residual
        vectors (right-hand sides) contain only active DOFs.
    verbose : bool
        If False, reduce verbosity.
    kwargs : dict, optional
        The variables (dictionary of (variable name) : (Variable
        instance)) to be used in the expression.

    Returns
    -------
    equation : Equation instance
        The equation that is ready to be evaluated.
    variables : Variables instance
        The variables used in the equation.
    """
    if kwargs is None:
        kwargs = {}

    if regions is not None:
        if isinstance(regions, Region):
            regions = [regions]

        regions = OneTypeList(Region, regions)

    else:
        regions = fields[list(fields.keys())[0]].domain.regions

    # Create temporary variables.
    aux_vars = Variables(variables)

    if extra_args is None:
        extra_args = kwargs

    else:
        extra_args = copy(extra_args)
        extra_args.update(kwargs)

    if ts is not None:
        extra_args.update({'ts' : ts})

    equations = Equations.from_conf({'tmp' : expression},
                                    aux_vars, regions, materials, integrals,
                                    user=extra_args, verbose=verbose)
    equations.collect_conn_info()

    # The true variables used in the expression.
    variables = equations.variables
    if auto_init:
        for var in variables:
            var.init_data(step=0)

    if mode == 'weak':
        equations.time_update(ts, ebcs, epbcs, lcbcs, functions,
                              active_only=active_only, verbose=verbose)

    else:
        setup_extra_data(equations.conn_info)

    return equations, variables


def eval_equations(equations, variables, names=None, preserve_caches=False,
                   mode='eval', dw_mode='vector', term_mode=None,
                   active_only=True, verbose=True):
    """
    Evaluate the equations.

    Parameters
    ----------
    equations : Equations instance
        The equations returned by :func:`create_evaluable()`.
    variables : Variables instance
        The variables returned by :func:`create_evaluable()`.
    names : str or sequence of str, optional
        Evaluate only equations of the given name(s).
    preserve_caches : bool
        If True, do not invalidate evaluate caches of variables.
    mode : one of 'eval', 'el_avg', 'qp', 'weak'
        The evaluation mode - 'weak' means the finite element
        assembling, 'qp' requests the values in quadrature points,
        'el_avg' element averages and 'eval' means integration over
        each term region.
    dw_mode : 'vector' or 'matrix'
        The assembling mode for 'weak' evaluation mode.
    term_mode : str
        The term call mode - some terms support different call modes
        and depending on the call mode different values are
        returned.
    active_only : bool
        If True, in 'weak' mode, the (tangent) matrices and residual
        vectors (right-hand sides) contain only active DOFs.
    verbose : bool
        If False, reduce verbosity.

    Returns
    -------
    out : dict or result
        The evaluation result. In 'weak' mode it is the vector or sparse
        matrix, depending on `dw_mode`. Otherwise, it is a dict of results with
        equation names as keys or a single result for a single equation.
    """
    asm_obj = None

    if mode == 'weak':
        if dw_mode == 'vector':
            asm_obj = equations.create_stripped_state_vector()

        else:
            asm_obj = equations.create_matrix_graph(active_only=active_only,
                                                    verbose=verbose)

    if not preserve_caches:
        equations.invalidate_term_caches()

    out = equations.evaluate(names=names, mode=mode, dw_mode=dw_mode,
                             term_mode=term_mode, asm_obj=asm_obj)

    if variables.has_lcbc and mode == 'weak':
        mtx_lcbc = variables.mtx_lcbc
        if dw_mode == 'vector':
            out = mtx_lcbc.T * out

        elif dw_mode == 'matrix':
            out = mtx_lcbc.T * out * mtx_lcbc
            out = out.tocsr()
            out.sort_indices()

    return out

def eval_in_els_and_qp(expression, iels, coors,
                       fields, materials, variables,
                       functions=None, mode='eval', term_mode=None,
                       extra_args=None, active_only=True, verbose=True,
                       kwargs=None):
    """
    Evaluate an expression in given elements and points.

    Parameters
    ----------
    expression : str
        The expression to evaluate.
    fields : dict
        The dictionary of fields used in `variables`.
    materials : Materials instance
        The materials used in the expression.
    variables : Variables instance
        The variables used in the expression.
    functions : Functions instance, optional
        The user functions for materials etc.
    mode : one of 'eval', 'el_avg', 'qp'
        The evaluation mode - 'qp' requests the values in quadrature points,
        'el_avg' element averages and 'eval' means integration over
        each term region.
    term_mode : str
        The term call mode - some terms support different call modes
        and depending on the call mode different values are
        returned.
    extra_args : dict, optional
        Extra arguments to be passed to terms in the expression.
    active_only : bool
        If True, in 'weak' mode, the (tangent) matrices and residual
        vectors (right-hand sides) contain only active DOFs.
    verbose : bool
        If False, reduce verbosity.
    kwargs : dict, optional
        The variables (dictionary of (variable name) : (Variable
        instance)) to be used in the expression.

    Returns
    -------
    out : array
        The result of the evaluation.
    """
    weights = nm.ones_like(coors[:, 0])
    integral = Integral('ie', coors=coors, weights=weights)

    domain = list(fields.values())[0].domain

    region = Region('Elements', 'given elements', domain, '')
    region.cells = iels
    region.update_shape()
    domain.regions.append(region)

    for field in six.itervalues(fields):
        field.clear_mappings(clear_all=True)
        field.clear_qp_base()

    aux = create_evaluable(expression, fields, materials,
                           variables.itervalues(), Integrals([integral]),
                           functions=functions, mode=mode,
                           extra_args=extra_args, active_only=active_only,
                           verbose=verbose, kwargs=kwargs)
    equations, variables = aux

    out = eval_equations(equations, variables,
                         preserve_caches=False,
                         mode=mode, term_mode=term_mode,
                         active_only=active_only)
    domain.regions.pop()

    return out

def assemble_by_blocks(conf_equations, problem, ebcs=None, epbcs=None,
                       dw_mode='matrix', active_only=True):
    """Instead of a global matrix, return its building blocks as defined in
    `conf_equations`. The name and row/column variables of each block have to
    be encoded in the equation's name, as in::

        conf_equations = {
          'A,v,u' : "dw_lin_elastic.i1.Y2( inclusion.D, v, u )",
        }

    Notes
    -----
    `ebcs`, `epbcs` must be either lists of BC names, or BC configuration
    dictionaries.
    """
    if isinstance( ebcs, list ) and isinstance( epbcs, list ):
        bc_mode = 0
    elif isinstance( ebcs, dict ) and isinstance( epbcs, dict ):
        bc_mode = 1
    else:
        raise TypeError('bad BC!')

    matrices = {}
    for key, mtx_term in six.iteritems(conf_equations):
        ks = key.split( ',' )
        mtx_name, var_names = ks[0], ks[1:]
        output( mtx_name, var_names )

        problem.set_equations({'eq': mtx_term})
        variables = problem.get_variables()
        indx = variables.get_indx

        if bc_mode == 0:
            problem.select_bcs( ebc_names = ebcs, epbc_names = epbcs )

        else:
            problem.time_update(ebcs=ebcs, epbcs=epbcs)

        ir = indx( var_names[0], stripped = True, allow_dual = True )
        ic = indx( var_names[1], stripped = True, allow_dual = True )

        problem.update_materials()
        mtx = problem.evaluate(mtx_term, auto_init=True,
                               mode='weak', dw_mode='matrix',
                               copy_materials=False, active_only=active_only)
        matrices[mtx_name] = mtx[ir,ic]

    return matrices
