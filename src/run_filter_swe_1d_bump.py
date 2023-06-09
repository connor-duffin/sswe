import h5py
import logging
import time

import fenics as fe
import numpy as np
import xarray as xr

from itertools import product
from multiprocessing import Pool
from argparse import ArgumentParser
from statfenics.utils import build_observation_operator
from swe_filter import ShallowOneKalman, ShallowOneEx

# some setup fcns
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
fe.set_log_level(40)
np.random.seed(27)
norm = np.linalg.norm


# set up global vars
control = dict(nx=500, dt=1., theta=0.6, simulation="tidal_flow")


def compute_rmse(post, y_obs, H_obs, relative=False):
    """ Compute the RMSE. """
    y_post = H_obs @ post.mean
    error = norm(y_post - y_obs)
    if relative:
        return error / norm(y_obs)
    else:
        return error / len(y_obs)


def compute_errors(post, true, H_verts, relative=True):
    """ Compute the error norm. Computed on a regular grid. """
    v_post = H_verts @ post.mean
    v_true = H_verts @ true.du.vector().get_local()
    v_norm_diff = norm(v_post - v_true)

    if relative:
        return v_norm_diff / norm(v_true)
    else:
        return v_norm_diff


def run_model(data_file, nx_obs, nt_skip, k, s, nu, linear, output_dir,
              posterior=True):
    # TODO(connor): eventually most of these will be args
    stat_params = dict(rho_u=0., ell_u=1000.,
                       rho_h=2e-3, ell_h=1000.,
                       k=k, k_init_u=k, k_init_h=k,
                       hilbert_gp=True)

    params = dict(nu=nu, shore_start=s,
                  shore_height=5.,
                  bump_height=0., bump_centre=8000., bump_width=400)

    # keep fixed for now
    obs_system = dict(nt_skip=nt_skip, nx_obs=nx_obs, sigma_y=5e-2)

    if linear:
        swe = ShallowOneKalman(control=control,
                               params=params,
                               stat_params=stat_params,
                               lr=True)
    else:
        swe = ShallowOneEx(control=control,
                           params=params,
                           stat_params=stat_params,
                           lr=True)

    # set the simulation runtimes
    t_final = 12. * 60 * 60.
    nt = np.int64(np.round(t_final / control["dt"]))

    # first read in the data
    dat = xr.open_dataset(data_file)
    nt_obs = len([i for i in range(nt) if i % obs_system["nt_skip"] == 0])

    # do some double checking
    assert dat.attrs["shore_height"] == params["shore_height"]
    assert control["dt"] == (dat.coords["t"].values[1]
                             - dat.coords["t"].values[0])
    assert t_final <= dat.coords["t"].values[-1]
    np.testing.assert_allclose(dat.coords["x"].values, swe.x_coords.flatten())

    # build observation/interpolation operators
    idx_obs = np.linspace(50, 100, nx_obs, dtype="int")
    x_obs = dat.coords["x"].values[idx_obs][:, np.newaxis]
    y_obs = dat["h"].values[1:, idx_obs]  # dont include IC

    # more double checking
    assert (x_obs[0] >= 1000. and x_obs[-1] <= 2000.)

    H_obs = build_observation_operator(x_obs, swe.W, sub=1, out="scipy")
    H_u_verts = build_observation_operator(swe.x_coords, swe.W, sub=0)
    H_h_verts = build_observation_operator(swe.x_coords, swe.W, sub=1)

    # setup output storage: save every thin'th iteration of the mean/var
    thin = 10 * 60
    nt_save = len([i for i in range(nt) if i % thin == 0])

    t_output = np.zeros((nt_save + 1, ))
    u_mean_output = np.zeros((nt_save + 1, swe.n_vertices))
    h_mean_output = np.zeros((nt_save + 1, swe.n_vertices))
    u_var_output = np.zeros((nt_save + 1, swe.n_vertices))
    h_var_output = np.zeros((nt_save + 1, swe.n_vertices))

    t_checkpoint = 0.
    mean_checkpoint = np.zeros((swe.n_dofs, ))
    cov_sqrt_checkpoint = np.zeros((swe.n_dofs, swe.k))

    # data-based outputs
    t_obs = np.zeros((nt_obs, ))
    rmse_output = np.zeros((nt_obs, ))
    rmse_rel_output = np.zeros((nt_obs, ))

    # posterior corrections
    if posterior:
        # save corrections (thinned across time)
        # u_correction = np.zeros((nt_save, swe.n_vertices))
        # h_correction = np.zeros((nt_save, swe.n_vertices))

        # save log marginal likelihoods
        lml_output = np.zeros((nt_obs, ))

    # store outputs
    t_output[0] = 0.
    u_mean_output[0, :] = H_u_verts @ swe.du_prev.vector().get_local()
    h_mean_output[0, :] = H_h_verts @ swe.du_prev.vector().get_local()
    u_var_output[0, :] = np.sum((H_u_verts @ swe.cov_sqrt)**2, axis=1)
    h_var_output[0, :] = np.sum((H_h_verts @ swe.cov_sqrt)**2, axis=1)

    # TODO(connor): sort out some way of doing the pattern subs.
    output_file_stem = "/{linearity}-{mtype}".format(
        linearity="linear" if linear else "nonlinear",
        mtype="posterior" if posterior else "prior"
    ) + "-s-{s:.1f}-nx_obs-{nx_obs:d}-nt_skip-{nt_skip:d}-nu-{nu:.2e}-k-{k:d}.h5".format(
        s=s,
        nx_obs=nx_obs,
        nt_skip=nt_skip,
        nu=nu,
        k=k)
    output_file = output_dir + output_file_stem
    output = h5py.File(output_file, "w")
    logger.info("saving output to %s", output)

    metadata = {**control, **stat_params, **obs_system}
    for name, val in metadata.items():
        output.attrs.create(name, val)

    output.attrs.create("s", s)
    output.attrs.create("nu", nu)
    output.attrs.create("linear", linear)
    output.attrs.create("posterior", posterior)

    t = 0.
    i_save = 0
    i_update = 0
    logger.info("%s starting running", output_file_stem)
    for i in range(nt):
        try:
            # push model forward every timestep
            t += swe.dt
            swe.prediction_step(t)

            # observe the data
            if i % obs_system["nt_skip"] == 0:
                y = y_obs[i, :]
                np.testing.assert_approx_equal(
                    t, dat.coords["t"].values[i + 1])

                if posterior:
                    # compute log-marginal likelihood and update
                    lml_output[i_update] = swe.compute_lml(
                        y, H_obs, obs_system["sigma_y"])

                    correction = swe.update_step(
                        y, H_obs, obs_system["sigma_y"],
                        return_correction=True)

                # compute RMSE
                rmse_output[i_update] = compute_rmse(swe, y, H_obs, False)
                rmse_rel_output[i_update] = compute_rmse(swe, y, H_obs, True)
                t_obs[i_update] = t
                i_update += 1

            # set to previous
            swe.set_prev()

            # store outputs every thin'th iteration
            if i % thin == 0:
                t_output[i_save] = t

                # u and h corrections
                # u_correction[i_save] = H_u_verts @ correction
                # h_correction[i_save] = H_h_verts @ correction

                # means
                u_mean_output[i_save, :] = H_u_verts @ swe.mean
                h_mean_output[i_save, :] = H_h_verts @ swe.mean

                # variances
                u_var_output[i_save, :] = np.sum(
                    (H_u_verts @ swe.cov_sqrt)**2, axis=1)
                h_var_output[i_save, :] = np.sum(
                    (H_h_verts @ swe.cov_sqrt)**2, axis=1)

                # checkpointing
                t_checkpoint = t
                mean_checkpoint[:] = swe.mean.copy()
                cov_sqrt_checkpoint[:] = swe.cov_sqrt.copy()
                i_save += 1

        except RuntimeError:
            logger.error("Filter, nu = %.5f failed at t= %.5f, exiting", nu, t)
            break

    # means and vars
    logger.info("%s finished running", output_file_stem)
    output.create_dataset("t", data=t_output)
    output.create_dataset("u_mean", data=u_mean_output)
    output.create_dataset("u_var", data=u_var_output)
    output.create_dataset("h_mean", data=h_mean_output)
    output.create_dataset("h_var", data=h_var_output)

    # checkpoints
    output.create_dataset("t_checkpoint", data=t_checkpoint)
    output.create_dataset("mean_checkpoint", data=mean_checkpoint)
    output.create_dataset("cov_sqrt_checkpoint", data=cov_sqrt_checkpoint)

    # outputs creation, etc
    output.create_dataset("t_obs", data=t_obs)
    output.create_dataset("rmse", data=rmse_output)
    output.create_dataset("rmse_rel", data=rmse_rel_output)

    if posterior:
        output.create_dataset("lml", data=lml_output)

        # output.create_dataset("u_correction", data=u_correction)
        # output.create_dataset("h_correction", data=h_correction)

    output.close()
    return i


if __name__ == "__main__":
    # initialize timer
    start_time = time.time()

    # read in from arguments
    parser = ArgumentParser()
    parser.add_argument("--n_threads", type=int)
    parser.add_argument("--data_file", type=str)
    parser.add_argument("--posterior", action="store_true")
    parser.add_argument("--linear", action="store_true")
    parser.add_argument("--nx_obs", nargs="+", type=int)  # default = 1
    parser.add_argument("--nt_skip", nargs="+", type=int)  # default = 30
    parser.add_argument("--nu", nargs="+", type=float)  # default = 1.
    parser.add_argument("--s", nargs="+", type=float)  # default = 1000.
    parser.add_argument("--k", nargs="+", type=int)  # default = 32
    parser.add_argument("--output_dir", type=str)
    args = parser.parse_args()

    p = Pool(args.n_threads)
    model_args = []
    for a in product(args.nx_obs, args.nt_skip, args.k, args.s, args.nu):
        model_args.append(
            (args.data_file, *a, args.linear, args.output_dir, args.posterior))

    out = p.starmap(run_model, model_args)

    # log wallclock time
    elapsed_time = time.time() - start_time
    logger.info("Elapsed time = %f", elapsed_time)
