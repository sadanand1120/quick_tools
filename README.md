# quick_tools

Small command-line utilities.

## Install

```bash
pip install git+https://github.com/sadanand1120/quick_tools.git
```

## PLY viewer

Serve a simple point-cloud `.ply` file in a browser:

```bash
quick-tools ply-viewer /path/to/cloud.ply
```

Open it directly in a local Open3D window with no browser downsampling:

```bash
quick-tools ply-viewer /path/to/cloud.ply --local
```

`--local` expects `open3d` to already be installed in the environment.

Choose a port:

```bash
quick-tools ply-viewer /path/to/cloud.ply --port 8123
```

If you are on a remote machine, the command prints an SSH port-forward example you can run from your local machine.

Very large point-cloud PLY files are automatically downsampled before being sent to the browser.

You can also set a point size:

```bash
quick-tools ply-viewer /path/to/cloud.ply --point-size 2.5
quick-tools ply-viewer /path/to/cloud.ply --local --point-size 3.0
```

View two PLY files with synchronized browser controls:

```bash
quick-tools ply-viewer /path/to/main.ply --and /path/to/other.ply
```

### PLY pipeline

`ply-viewer` acts as a small middleman:

1. Load the raw PLY.
2. Validate and extract only `x y z` plus one optional RGB vertex property set.
3. If multiple RGB sets exist, ask which one to keep.
4. Ignore extra vertex fields and all non-vertex elements, including faces.
5. Emit a clean vertex-only PLY for Three.js in the browser or Open3D with `--local`.

### Expected PLY contract

- Header starts with `ply`.
- Format is `ascii`, `binary_little_endian`, or `binary_big_endian`.
- `element vertex N` exists, is first, and has `N > 0`.
- Required vertex properties are named exactly `x`, `y`, and `z`.
- `x/y/z` types must be `float`, `float32`, `double`, `float64`, `int`, or `int32`.
- Optional color sets can be full `r g b`, full `red green blue`, or prefixed forms like `normals_r normals_g normals_b` and `normals_red normals_green normals_blue`.
- Color types must be `uchar` or `uint8`, meaning values are `0-255`.
- If multiple complete color sets are found, `ply-viewer` prompts in the terminal and keeps only the selected one.
- Extra scalar vertex properties are ignored.
- Vertex list properties are not supported.
- Elements after `vertex`, such as `face`, are ignored.
