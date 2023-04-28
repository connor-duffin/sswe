# 1d immersed bump
# ----------------
ks = 4 8 32 64 128
cs = 1000 2000 3000 4000 5000
nus = 1 100 1000 10000
nt_skips = 1 30 150 300

# constants
data_file = data/h_bump_test.nc
bump_output_dir = outputs/swe-bump-tidal-redo
n_threads = 17
k_default = 32
nt_skip_default = 30

data/h_bump.nc:
	python3 src/generate_data_swe_1d_bump.py \
		--output_file $@

bump_priors_linear:
	python3 src/run_filter_swe_1d_bump.py \
		--linear --n_threads $(n_threads) --nt_skip $(nt_skip_default) --k $(k_default) \
		--nu $(nus) --c $(cs) \
		--data_file $(data_file) --output_dir $(bump_output_dir)

bump_filters_linear:
	python3 src/run_filter_swe_1d_bump.py \
		--linear --n_threads $(n_threads) --nt_skip $(nt_skips) --k $(k_default) --posterior \
		--nu $(nus) --c $(cs) \
		--data_file $(data_file) --output_dir $(bump_output_dir)

bump_priors_nonlinear:
	python3 src/run_filter_swe_1d_bump.py \
		--n_threads $(n_threads) --nt_skip $(nt_skip_default) --k $(k_default) \
		--nu $(nus) --c $(cs) \
		--data_file $(data_file) --output_dir $(bump_output_dir)

bump_filters_nonlinear:
	python3 src/run_filter_swe_1d_bump.py \
		--n_threads $(n_threads) --nt_skip $(nt_skips) --k $(k_default) --posterior \
		--nu $(nus) --c $(cs) \
		--data_file $(data_file) --output_dir $(bump_output_dir)

all_bump_prior: bump_priors_nonlinear bump_priors_linear

all_bump_post: bump_filters_nonlinear bump_filters_linear

all_bump_prior_post: all_bump_prior all_bump_post

clean_all_bump_outputs:
	rm $(bump_output_dir)/*

# (old!) deterministic models
$(bump_output_dir)/nu-%.h5: src/run_swe_1d_bump.py
	python3 $< \
		--nu $* --output_file $@ \
		--nx 500 --dt 0.01 --nt_save 10

$(bump_output_dir)/linear.h5: src/run_swe_1d_bump.py
	python3 $< \
		--output_file $@ --linear \
		--nx 500 --dt 0.01 --nt_save 10
