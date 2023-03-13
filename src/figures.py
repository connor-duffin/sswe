import palettable

figure_sizes = {
    "halfwidth": 3.54,
    "fullwidth": 7.2
}

color_diverge = palettable.cartocolors.diverging.Geyser_3.mpl_colormap
color_cycle = palettable.cartocolors.qualitative.Prism_6.mpl_colors
color_map = palettable.matplotlib.Viridis_6.mpl_colormap


def texp(string, dollar_surround=True):
    if "e" in string:
        string_split = string.split('e')
        exponent = string_split[-1]

        exponent_sign = exponent[0]
        exponent_value = exponent[1:].lstrip("0")
        if exponent_sign == "+":
            exponent_sign = ""

        exponent = f"{{{exponent_sign + exponent_value}}}"
        if exponent == "{}":
            # if zero exponent: just return the value
            string = string_split[0]
        elif float(string_split[0]) == 1.:
            # if 1x10^{k} return 10^{k}
            string_split[0] = r"10^"
            string_split[-1] = exponent
            string = ''.join(string_split)
        else:
            # otherwise convert to Ax10^{k}
            string_split.insert(1, r" \times 10^")
            string_split[-1] = exponent
            string = ''.join(string_split)

    if dollar_surround:
        return fr"${string}$"
    else:
        return string
