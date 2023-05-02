# 1d immersed bump
# ----------------
ks = 4 8 32 64 128
s = 2000 3500 5000 6500 8000
nus = 1 1000 10000 50000 100000
nx_obs = 1 2 5
nt_skips = 1 30 60 120 180

# constants
data_file = data/h_shore.nc
dgp_file = data/h_shore_dgp.nc
model_output_dir = outputs/swe-tidal-redo-sparse
n_threads = 8
k_default = 32
nt_skip_default = 30

$(dgp_file):
	python3 src/generate_data_swe_1d_bump.py --output_file $@

$(data_file):
	python3 src/generate_data_swe_1d_bump.py --add_noise --output_file $@

priors_linear:
	time -v python3 src/run_filter_swe_1d_bump.py \
		--linear --n_threads $(n_threads) --nx_obs $(nx_obs) --nt_skip $(nt_skip_default) --k $(k_default) \
		--nu $(nus) --s $(s) \
		--data_file $(data_file) --output_dir $(model_output_dir)

filters_linear:
	time -v python3 src/run_filter_swe_1d_bump.py \
		--linear --n_threads $(n_threads) --nx_obs $(nx_obs) --nt_skip $(nt_skips) --k $(k_default) --posterior \
		--nu $(nus) --s $(s) \
		--data_file $(data_file) --output_dir $(model_output_dir)

priors_nonlinear:
	time -v python3 src/run_filter_swe_1d_bump.py \
		--n_threads $(n_threads) --nx_obs $(nx_obs) --nt_skip $(nt_skip_default) --k $(k_default) \
		--nu $(nus) --s $(s) \
		--data_file $(data_file) --output_dir $(model_output_dir)

filters_nonlinear:
	time -v python3 src/run_filter_swe_1d_bump.py \
		--n_threads $(n_threads) --nx_obs $(nx_obs) --nt_skip $(nt_skips) --k $(k_default) --posterior \
		--nu $(nus) --s $(s) \
		--data_file $(data_file) --output_dir $(model_output_dir)

all_nonlinear: priors_nonlinear filters_nonlinear

all_linear: priors_linear filters_linear

all_prior: priors_nonlinear priors_linear

all_post: filters_nonlinear filters_linear

all_prior_post: all_post all_prior

clean_all_outputs:
	rm $(model_output_dir)/*

# (old!) deterministic models
$(model_output_dir)/nu-%.h5: src/run_swe_1d_bump.py
	python3 $< \
		--nu $* --output_file $@ \
		--nx 500 --dt 0.01 --nt_save 10

$(model_output_dir)/linear.h5: src/run_swe_1d_bump.py
	python3 $< \
		--output_file $@ --linear \
		--nx 500 --dt 0.01 --nt_save 10
