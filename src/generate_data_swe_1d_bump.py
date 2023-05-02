import logging
import xarray as xr
import numpy as np

from argparse import ArgumentParser
from fenics import set_log_level
from swe import ShallowOne
from tqdm import tqdm

set_log_level(40)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

parser = ArgumentParser()
parser.add_argument("--add_noise", action="store_true")
parser.add_argument("--output_file", type=str)
args = parser.parse_args()

SIGMA_Y = 5e-2
T_FINAL = 24 * 60 * 60

settings = dict(nx=500, dt=2., theta=0.6, nu=1., shore_start=2000)
control = dict(nx=settings["nx"],
               dt=settings["dt"],
               theta=0.6,
               simulation="tidal_flow")
params = dict(nu=settings["nu"],
              shore_start=settings["shore_start"],
              shore_height=5.,
              bump_height=0.,
              bump_centre=8000.,
              bump_width=400)
swe_dgp = ShallowOne(control=control, params=params)
logger.info(control)
logger.info(params)

# set the observation system
nt = np.int64(np.round(T_FINAL / settings["dt"]))
t_grid = np.linspace(0., T_FINAL, nt + 1)

# store outputs
u_obs = np.zeros((nt + 1, settings["nx"] + 1))  # include step for final time
h_obs = np.zeros((nt + 1, settings["nx"] + 1))  # include step for final time
u_obs[0, :] = swe_dgp.du.compute_vertex_values()[:(settings["nx"] + 1)]
h_obs[0, :] = swe_dgp.du.compute_vertex_values()[(settings["nx"] + 1):]

t = 0.
logger.info("starting SWE run")
for i in tqdm(range(nt)):
    t += swe_dgp.dt
    swe_dgp.solve(t)
    u_obs[i + 1, :] = swe_dgp.du.compute_vertex_values()[:(settings["nx"] + 1)]
    h_obs[i + 1, :] = swe_dgp.du.compute_vertex_values()[(settings["nx"] + 1):]

    if args.add_noise:
        h_obs[i + 1, :] += SIGMA_Y * np.random.normal(
            size=h_obs[i + 1, :].shape)

# HACK(connor): autoconvert to dataset
u_out = xr.DataArray(data=u_obs,
                     coords=dict(t=t_grid, x=swe_dgp.x_coords.flatten()),
                     attrs={**settings, **params},
                     name="u")
h_out = xr.DataArray(data=h_obs,
                     coords=dict(t=t_grid, x=swe_dgp.x_coords.flatten()),
                     attrs={**settings, **params},
                     name="h")
out = xr.merge([u_out, h_out])

logger.info("storing outputs into %s", args.output_file)
out.to_netcdf(args.output_file)
