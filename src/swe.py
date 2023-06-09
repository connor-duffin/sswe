""" Solve the Shallow-water equations in non-conservative form. """
import logging

import numpy as np
import fenics as fe

# initialise the logger
logger = logging.getLogger(__name__)

# use default Fenics MPI comm (itself uses mpi4py)
comm = fe.MPI.comm_world
rank = comm.Get_rank()


H_TIDAL_BC = fe.Expression(
    "2 * (1 + cos(pi * ((4 * t) / 86400)))", t=0., degree=4)
H_INIT_BUMP = fe.Expression("exp(- pow(2 * (x[0] - 10), 2)) / 40", degree=2)


class PiecewiseIC(fe.UserExpression):
    def __init__(self, L):
        super().__init__()
        self.L = L

    def eval(self, values, x):
        if x[0] < self.L + fe.DOLFIN_EPS:
            values[0] = 5.
        else:
            values[0] = 0.


class BumpTopo(fe.UserExpression):
    def __init__(self, c, L):
        super().__init__()
        self.c = c
        self.L = L

        self.lower = c - 2
        self.upper = c + 2

    def eval(self, values, x):
        if x[0] <= self.upper and x[0] >= self.lower:
            values[0] = 0.5 * (0.6 + 0.1 * (x[0] - self.c)**2)
        else:
            values[0] = 0.5


# subdomain for periodic boundary condition
class PeriodicBoundary(fe.SubDomain):
    def inside(self, x, on_boundary):
        return bool(x[0] < fe.DOLFIN_EPS and x[0] > -fe.DOLFIN_EPS
                    and on_boundary)

    # map right boundary to left boundary
    def map(self, x, y):
        y[0] = x[0] - 10


class ShallowOneLinear:
    def __init__(self, control, params):
        # read in parameters
        self.nx = control["nx"]
        self.dt = control["dt"]
        self.nu = params["nu"]

        # setup parameters etc
        self.shore_start = params["shore_start"]
        self.shore_height = params["shore_height"]

        self.bump_width = params["bump_width"]
        self.bump_height = params["bump_height"]
        self.bump_centre = params["bump_centre"]
        self.L = 10_000

        # setup mesh and function spaces
        self.mesh = fe.IntervalMesh(self.nx, 0., self.L)
        self.x = fe.SpatialCoordinate(self.mesh)

        U = fe.FiniteElement("P", self.mesh.ufl_cell(), 2)
        H = fe.FiniteElement("P", self.mesh.ufl_cell(), 1)
        TH = fe.MixedElement([U, H])
        self.W = fe.FunctionSpace(self.mesh, TH,
                                  constrained_domain=PeriodicBoundary())
        self.U, self.H = self.W.split()
        self.U_space = self.U.collapse()
        self.H_space = self.H.collapse()

        self.x_coords = self.mesh.coordinates()
        self.n_vertices = len(self.x_coords)
        self.x_dofs = self.W.tabulate_dof_coordinates()
        self.n_dofs = self.x_dofs.shape[0]

        self.u_dofs = self.W.sub(0).dofmap().dofs()
        self.h_dofs = self.W.sub(1).dofmap().dofs()

        self.x_dofs_u = self.x_dofs[self.u_dofs, :]
        self.x_dofs_h = self.x_dofs[self.h_dofs, :]

        # HACK: introduce new function space to construct interpolant
        nu = fe.Constant(self.nu)
        g = fe.Constant(9.8)

        def _right(x, on_boundary):
            return x[0] >= (self.L - fe.DOLFIN_EPS)

        def _left(x, on_boundary):
            return x[0] <= fe.DOLFIN_EPS

        self._right = _right
        self._left = _left

        u_right = fe.Constant(0.0)
        bc_u_right = fe.DirichletBC(self.W.sub(0), u_right, self._right)

        self.tidal_bc = H_TIDAL_BC
        bc_h_left = fe.DirichletBC(self.W.sub(1), self.tidal_bc, self._left)
        self.bcs = [bc_u_right, bc_h_left]

        H = fe.Expression(
            f"30 - {self.shore_height} * (1 + tanh((x[0] - {self.shore_start}) / 2000))" +
            f"-{self.bump_height} * exp(-0.5 / ({self.bump_width**2}) * pow(x[0] - {self.bump_centre}, 2))",
            degree=4)
        self.H = fe.interpolate(H, self.H_space)
        u, h = fe.TrialFunctions(self.W)
        v_u, v_h = fe.TestFunctions(self.W)

        self.du_prev = fe.Function(self.W)
        u_prev, h_prev = fe.split(self.du_prev)

        dt = fe.Constant(self.dt)
        self.theta = control["theta"]
        u_theta = self.theta * u + (1 - self.theta) * u_prev
        h_theta = self.theta * h + (1 - self.theta) * h_prev

        # inviscid flow
        self.F = (fe.inner(h - h_prev, v_h) / dt * fe.dx
                  + (self.H * u_theta).dx(0) * v_h * fe.dx
                  + fe.inner(u - u_prev, v_u) / dt * fe.dx
                  + nu * fe.inner(fe.grad(u_theta), fe.grad(v_u)) * fe.dx
                  + g * h_theta.dx(0) * v_u * fe.dx)

        self.du = fe.Function(self.W)
        self.du_vertices = np.copy(self.du.compute_vertex_values())

        self.a, self.l = fe.system(self.F)
        self.problem = fe.LinearVariationalProblem(
            self.a, self.l, self.du, bcs=self.bcs)
        self.solver = fe.LinearVariationalSolver(self.problem)

    def solve(self, t, set_prev=True):
        self.tidal_bc.t = t
        self.solver.solve()
        if set_prev:
            fe.assign(self.du_prev, self.du)

    def compute_energy(self):
        u, h = fe.split(self.du)
        return fe.assemble(u**2 * fe.dx) / 2.

    def set_curr_vector(self, du_vec):
        self.du.vector().set_local(du_vec)

    def set_prev_vector(self, du_vec):
        self.du_prev.vector().set_local(du_vec)

    def get_vertex_values(self):
        self.du_vertices[:] = self.du.compute_vertex_values()
        return (self.du_vertices[:self.n_vertices],
                self.du_vertices[self.n_vertices:])

    def get_vertex_values_prev(self):
        self.du_vertices[:] = self.du_prev.compute_vertex_values()
        return (self.du_vertices[:self.n_vertices],
                self.du_vertices[self.n_vertices:])

    def setup_checkpoint(self, checkpoint_file):
        """ Set up the checkpoint file, writing the appropriate things etc. """
        logger.info(f"storing outputs in {checkpoint_file}")
        self.checkpoint = fe.HDF5File(self.mesh.mpi_comm(), checkpoint_file, "w")

    def checkpoint_save(self, t):
        """ Save the simulation at the current time. """
        self.checkpoint.write(self.du, "/du", t)

    def checkpoint_close(self):
        self.checkpoint.close()


class ShallowOne:
    def __init__(self, control, params):
        self.nx = control["nx"]
        self.dt = control["dt"]
        self.simulation = control["simulation"]

        # HACK(connor) use 'c' and 'bump_centre' to parameterise both
        if self.simulation == "dam_break":
            self.L = 2000
        elif self.simulation == "tidal_flow":
            self.shore_start = params["shore_start"]
            self.shore_height = params["shore_height"]

            self.bump_width = params["bump_width"]
            self.bump_height = params["bump_height"]
            self.bump_centre = params["bump_centre"]
            self.L = 10_000
        elif self.simulation == "immersed_bump":
            self.bump_centre = params["bump_centre"]
            self.L = 25.
        else:
            raise ValueError("Simulation setup not recognised")

        # read in parameter values
        self.nu = params["nu"]

        # setup mesh and function spaces
        self.mesh = fe.IntervalMesh(self.nx, 0., self.L)
        self.x = fe.SpatialCoordinate(self.mesh)
        self.boundaries = fe.MeshFunction("size_t", self.mesh,
                                          self.mesh.topology().dim() - 1, 0)
        self.dx = self.mesh.hmax()
        logger.info(f"CFL: {np.sqrt(9.81 * 10) * self.dt / self.dx:.5f}")

        U = fe.FiniteElement("P", self.mesh.ufl_cell(), 2)
        H = fe.FiniteElement("P", self.mesh.ufl_cell(), 1)
        TH = fe.MixedElement([U, H])
        self.W = fe.FunctionSpace(self.mesh, TH)
        self.U, self.H = self.W.split()
        self.U_space = self.U.collapse()
        self.H_space = self.H.collapse()

        self.x_coords = self.mesh.coordinates()
        self.n_vertices = len(self.x_coords)
        self.x_dofs = self.W.tabulate_dof_coordinates()
        self.n_dofs = self.x_dofs.shape[0]

        self.u_dofs = self.W.sub(0).dofmap().dofs()
        self.h_dofs = self.W.sub(1).dofmap().dofs()

        self.x_dofs_u = self.x_dofs[self.u_dofs, :]
        self.x_dofs_h = self.x_dofs[self.h_dofs, :]

        if self.simulation == "dam_break":
            self.H = fe.Constant(5.0)

            p = PiecewiseIC(self.L // 2)
            ic = fe.interpolate(p, self.H_space)
        elif self.simulation == "tidal_flow":
            H = fe.Expression(
                f"30 - {self.shore_height} * (1 + tanh((x[0] - {self.shore_start})/2000))" +
                f"-{self.bump_height} * exp(-0.5 / ({self.bump_width**2}) * pow(x[0] - {self.bump_centre}, 2))",
                degree=4)
            self.H = fe.interpolate(H, self.H_space)
        elif self.simulation == "immersed_bump":
            # set H
            H = BumpTopo(self.bump_centre, self.L)
            self.H = fe.interpolate(H, self.H_space)

        self.du = fe.Function(self.W)
        self.du_vertices = np.copy(self.du.compute_vertex_values())
        u, h = fe.split(self.du)

        self.du_prev = fe.Function(self.W)
        u_prev, h_prev = fe.split(self.du_prev)
        v_u, v_h = fe.TestFunctions(self.W)

        g = fe.Constant(9.8)
        nu = fe.Constant(self.nu)
        dt = fe.Constant(self.dt)

        self.theta = control["theta"]
        u_theta = self.theta * u + (1 - self.theta) * u_prev
        h_theta = self.theta * h + (1 - self.theta) * h_prev
        self.F = (fe.inner(u - u_prev, v_u) / dt * fe.dx
                  + u_prev * u_theta.dx(0) * v_u * fe.dx
                  + nu * fe.inner(fe.grad(u_theta), fe.grad(v_u)) * fe.dx
                  + g * h_theta.dx(0) * v_u * fe.dx
                  + fe.inner(h - h_prev, v_h) / dt * fe.dx
                  + ((self.H + h_theta) * u_theta).dx(0) * v_h * fe.dx)
        self.J = fe.derivative(self.F, self.du)

        # assemble RHS
        self.rhs = (- u * u.dx(0) * v_u * fe.dx
                    - 2 * nu * fe.inner(fe.grad(u), fe.grad(v_u)) * fe.dx
                    - g * h.dx(0) * v_u * fe.dx
                    - ((self.H + h) * u).dx(0) * v_h * fe.dx)
        self.rhs_derivative = fe.derivative(self.rhs, self.du)

        def _right(x, on_boundary):
            return x[0] >= (self.L - fe.DOLFIN_EPS)

        def _left(x, on_boundary):
            return x[0] <= fe.DOLFIN_EPS

        self._right = _right
        self._left = _left

        # set the IC's
        if self.simulation == "dam_break":
            for init in [self.du, self.du_prev]:
                fe.assign(init.sub(1), ic)

            h_left = fe.Constant(5.0)
            h_right = fe.Constant(0.0)

            bc_h_left = fe.DirichletBC(self.W.sub(1), h_left, self._left)
            bc_h_right = fe.DirichletBC(self.W.sub(1), h_right, self._right)
            self.bcs = [bc_h_left, bc_h_right]

            # add in boundary terms to the weak form
            self.F += v_h * u_prev * (
                self.H + h_right) * fe.ds - v_h * u_prev * (self.H +
                                                            h_left) * fe.ds
        elif self.simulation == "tidal_flow":
            u_right = fe.Constant(0.0)
            bc_u_right = fe.DirichletBC(self.W.sub(0), u_right, self._right)
            self.tidal_bc = H_TIDAL_BC
            bc_h_left = fe.DirichletBC(self.W.sub(1), self.tidal_bc, self._left)
            self.bcs = [bc_u_right, bc_h_left]
        elif self.simulation == "immersed_bump":
            for init in [self.du, self.du_prev]:
                ic = fe.interpolate(H_INIT_BUMP, self.H_space)
                fe.assign(init.sub(1), ic)

            def bounds(x, on_boundary):
                return on_boundary

            self.bcs = fe.DirichletBC(self.W.sub(1), fe.Constant(0.), bounds)

        problem = fe.NonlinearVariationalProblem(self.F, self.du, bcs=self.bcs, J=self.J)
        self.solver = fe.NonlinearVariationalSolver(problem)

        # vanilla fenics solver options
        prm = self.solver.parameters
        # prm['newton_solver']['absolute_tolerance'] = 1E-8
        # prm['newton_solver']['relative_tolerance'] = 1E-6
        # prm['newton_solver']['convergence_criterion'] = "incremental"
        # prm['newton_solver']['maximum_iterations'] = 50
        # prm['newton_solver']['relaxation_parameter'] = 0.5

        # PETSc SNES config
        prm["nonlinear_solver"] = "snes"
        prm["snes_solver"]["line_search"] = "bt"
        prm["snes_solver"]["linear_solver"] = "mumps"
        # prm["snes_solver"]["linear_solver"] = "gmres"
        # prm["snes_solver"]["preconditioner"] = "sor"
        # logger.info(f"Using {prm['snes_solver']['linear_solver']}"
        #             + f"w/PC {prm['snes_solver']['preconditioner']}")
        
        # solver convergence
        prm["snes_solver"]["relative_tolerance"] = 1e-6
        prm["snes_solver"]['absolute_tolerance'] = 1e-8
        prm["snes_solver"]["maximum_iterations"] = 50
        prm["snes_solver"]['error_on_nonconvergence'] = True

        # solver reporting
        prm["snes_solver"]['krylov_solver']['report'] = False
        prm["snes_solver"]['krylov_solver']['monitor_convergence'] = False

        # don't print outputs from the Newton solver
        prm["snes_solver"]["report"] = False

    @staticmethod
    def tidal_bc(t):
        return 2 * (1 + np.cos(np.pi * ((4 * t) / 86_400)))

    def compute_energy(self):
        u, h = fe.split(self.du)
        return fe.assemble(u**2 * fe.dx) / 2.

    def solve(self, t, set_prev=True):
        if self.simulation == "tidal_flow":
            self.tidal_bc.t = t

        self.solver.solve()

        if set_prev:
            fe.assign(self.du_prev, self.du)

    def set_curr_vector(self, du_vec):
        self.du.vector().set_local(du_vec)

    def set_prev_vector(self, du_vec):
        self.du_prev.vector().set_local(du_vec)

    def get_vertex_values(self):
        self.du_vertices[:] = self.du.compute_vertex_values()
        return (self.du_vertices[:self.n_vertices],
                self.du_vertices[self.n_vertices:])

    def get_vertex_values_prev(self):
        self.du_vertices[:] = self.du_prev.compute_vertex_values()
        return (self.du_vertices[:self.n_vertices],
                self.du_vertices[self.n_vertices:])

    def setup_checkpoint(self, checkpoint_file):
        """ Set up the checkpoint file, writing the appropriate things etc. """
        logger.info(f"storing outputs in {checkpoint_file}")
        self.checkpoint = fe.HDF5File(self.mesh.mpi_comm(), checkpoint_file, "w")

    def checkpoint_save(self, t):
        """ Save the simulation at the current time. """
        self.checkpoint.write(self.du, "/du", t)

    def checkpoint_close(self):
        self.checkpoint.close()
