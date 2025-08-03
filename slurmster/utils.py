import itertools
import re

def expand_grid(grid_dict):
    # grid_dict: { key: [v1, v2, ...], ...}
    keys = list(grid_dict.keys())
    vals = [grid_dict[k] for k in keys]
    combos = []
    for prod in itertools.product(*vals):
        combos.append(dict(zip(keys, prod)))
    return combos

def slugify_value(v):
    s = str(v)
    s = s.replace('/', '_').replace(' ', '_')
    s = re.sub(r'[^A-Za-z0-9_.-]+', '_', s)
    return s

def make_exp_name(params):
    parts = []
    for k in sorted(params.keys()):
        parts.append(f"{k}_{slugify_value(params[k])}")
    return "exp_" + "_".join(parts)

def substitute_placeholders(text, mapping):
    out = text
    for k, v in mapping.items():
        out = out.replace("{" + k + "}", str(v))
    return out
