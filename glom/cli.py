"""like jq, but with the full power of python in the spec.

Usage: python -m glom [FLAGS] [spec [target]]

Command-line interface to the glom library, providing nested data
access and data restructuring with the power of Python.


Flags:

  --help / -h                 show this help message and exit
  --target-file TARGET_FILE   path to target data source (optional)
  --target-format TARGET_FORMAT
                              format of the source data (json, python, toml,
                              or yaml) (defaults to 'json')
  --spec-file SPEC_FILE       path to glom spec definition (optional)
  --spec-format SPEC_FORMAT   format of the glom spec definition (json, python,
                              python-full) (defaults to 'python')
  --indent INDENT             number of spaces to indent the result, 0 to disable
                              pretty-printing (defaults to 2)
  --debug                     interactively debug any errors that come up
  --inspect                   interactively explore the data

try out:
`
curl -s https://api.github.com/repos/mahmoud/glom/events | python -m glom '[{"type": "type", "date": "created_at", "user": "actor.login"}]'

"""



import os
import ast
import sys
import json

from face import (Command,
                  Flag,
                  face_middleware,
                  PosArgSpec,
                  PosArgDisplay,
                  CommandLineError,
                  UsageError)
from face.utils import isatty
from boltons.iterutils import is_scalar

import glom
from glom import Path, GlomError, Inspect

# TODO: --default?

def glom_cli(target, spec, indent, debug, inspect, scalar):
    """Command-line interface to the glom library, providing nested data
    access and data restructuring with the power of Python.
    """
    pass






def console_main():
    _enable_debug = os.getenv('GLOM_CLI_DEBUG')
    if _enable_debug:
        print(sys.argv)
    try:
        sys.exit(main(sys.argv) or 0)
    except Exception:
        if _enable_debug:
            import pdb;pdb.post_mortem()
        raise


def mw_handle_target(target_text, target_format):
    """ Handles reading in a file specified in cli command.

    Args:
        target_text (str): The target data to load, as text
        target_format (str): Valid formats include `json`, `toml`, and `yml`/`yaml`
    Returns:
        The content of the file that you specified
    Raises:
        CommandLineError: Issue with file format or appropriate file reading package not installed.
    """
    pass








