# Exploring PDE-data misspecification with statFEM, via SWE

This repository accompanies our work on studying statFEM model misspecification
with 1D shallow water equations (SWE). Misspecification, in this sense, follows
the statistical definition whereby there employed likelihood is not the same
as that used to generate the data.

The code is structured as follows:

* `data` is an empty directory where the simulated data is generated.
* `figures` is an empty directory where the figures are generated.
* `notebooks` contains the Jupyter notebooks to conduct the output processing and generate figures.
* `outputs` is an empty directory where all the model outputs are generated.
* `src` houses all the code for the project, and unit tests.
* `makefile` contains the instructions to run the models, from `src`.

To run the unit tests run:

```{bash}
python3 -m pytest src
```

## Running the code

To compute the models and generate the data, we go from the makefile. To generate the data:

```{bash}
make data/h_shore.nc
```

Now, having this data, we can compute the model posteriors and
priors. To generate all the nonlinear model posteriors, across all
parameters, run

```{bash}
make filters_nonlinear
```

and for the linear models (again across all parameters)

```{bash}
make filters_linear
```

To compute the priors you run

```{bash}
make priors_nonlinear
```

And likewise for the linear priors

```{bash}
make priors_linear
```

To compute all posteriors and priors, across all parameters, simply run

```{bash}
make all_prior_post
```

To analyse the model outputs we assume that we have run all the posterior and priors, as detailed above. First, load up a jupyter lab session in this directory.

```{bash}
jupyter lab
```

Now, from this, navigate to the `notebooks` directory, where you should be able to access the appropriate notebooks for this work.

