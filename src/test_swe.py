import numpy as np
import fenics as fe

from numpy.testing import assert_allclose
from swe import ShallowOneLinear, ShallowOne


def test_shallowone_linear_init():
    control = {"nx": 32, "dt": 0.02, "theta": 1.0, "simulation": "tidal_flow"}
    params = {"nu": 1.0,
              "shore_start": 1000, "shore_height": 5,
              "bump_height": 0, "bump_width": 100, "bump_centre": 1000.}

    swe = ShallowOneLinear(control, params)
    assert len(swe.x_dofs_u) == 65
    assert len(swe.x_dofs_h) == 33
    assert len(swe.x_coords) == 33

    # check bilinear form stuff
    a, L = fe.lhs(swe.F), fe.rhs(swe.F)
    assert_allclose(fe.assemble(L).get_local(),
                    fe.assemble(swe.l).get_local())

    # check that topo is set OK
    H = swe.H.compute_vertex_values()
    assert H.shape == (33, )

    swe_nonlinear = ShallowOne(control=control, params=params)
    H_nonlinear = swe_nonlinear.H.compute_vertex_values()
    np.testing.assert_allclose(H, H_nonlinear)

    # check that the tidal BC is enforced OK
    # (and is the same across all)
    t_grid = np.linspace(0., 24. * 60. * 60., 20)
    def tbc(t): return 2 * (1 + np.cos(np.pi * ((4 * t) / 86400)))
    for t in t_grid:
        swe.tidal_bc.t = t
        assert_allclose(swe.tidal_bc.compute_vertex_values(swe.mesh),
                        tbc(t))

        swe_nonlinear.tidal_bc.t = t
        assert_allclose(swe_nonlinear.tidal_bc.compute_vertex_values(swe.mesh),
                        tbc(t))

    # check that initial DOFs are set OK
    u_prev, h_prev = swe.get_vertex_values_prev()
    np.testing.assert_allclose(u_prev, 0.)
    np.testing.assert_allclose(h_prev, 0.)

    # and run solve just to check that things work OK
    swe.solve(0. + swe.dt)


def test_shallowone_init():
    # re-instantiate with diff setup BCs
    control = {"nx": 32, "dt": 0.02, "theta": 1.0, "simulation": "tidal_flow"}
    params = {"nu": 1.0,
              "shore_start": 1000, "shore_height": 5,
              "bump_height": 0, "bump_width": 100, "bump_centre": 1000.}
    swe = ShallowOne(control, params)

    assert len(swe.x_dofs_u) == 65
    assert len(swe.x_dofs_h) == 33
    assert len(swe.x_coords) == 33

    # regression test for BC
    assert_allclose(swe.tidal_bc(1.), 4.)

    # now verify dam break scenario
    control["simulation"] = "dam_break"
    swe = ShallowOne(control, params)

    assert len(swe.x_dofs_u) == 65
    assert len(swe.x_dofs_h) == 33
    assert len(swe.x_coords) == 33

    # check that solving actually does something
    # (measured in the L2 norm)
    u_prev = np.copy(swe.du_prev.vector().get_local())
    swe.solve(0. + swe.dt)
    u_next = np.copy(swe.du.vector().get_local())
    assert np.linalg.norm(u_prev - u_next) >= 1e-6


def test_shallowone_vertices():
    # check that function computations look reasonable
    control = {"nx": 32, "dt": 0.02, "theta": 1.0, "simulation": "tidal_flow"}
    params = {"nu": 1.0,
              "shore_start": 1000, "shore_height": 5,
              "bump_height": 0, "bump_width": 100, "bump_centre": 1000.}
    swe = ShallowOne(control, params)

    du_true = fe.Expression(("t * sin(x[0])", "t * cos(x[0])"), t=2., degree=4)
    swe.du.interpolate(du_true)
    u, h = swe.get_vertex_values()

    assert_allclose(u, 2 * np.sin(swe.x_coords.flatten()))
    assert_allclose(h, 2 * np.cos(swe.x_coords.flatten()))
