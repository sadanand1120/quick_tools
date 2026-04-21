# quick_tools

Small command-line utilities.

## Install

```bash
pip install git+https://github.com/sadanand1120/quick_tools.git
```

## PLY viewer

Serve any `.ply` file in a browser:

```bash
quick-tools ply-viewer /path/to/cloud.ply
```

Choose a port:

```bash
quick-tools ply-viewer /path/to/cloud.ply --port 8123
```

If you are on a remote machine, the command prints an SSH port-forward example you can run from your local machine.

Very large binary point-cloud PLY files are automatically downsampled before being sent to the browser.
