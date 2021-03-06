"""SpatialAxis class"""

from datetime import datetime

import numpy as np
from netCDF4 import Dataset

from ..utils import class_name, create_dimensions_verify, create_vars


class SpatialAxis:
    """class for spatial axis related quantities"""

    def __init__(self, axisname=None, fname=None, defn_dict=None):
        """
        Initialize SpatialAxis object, from a file or a dict defining the axis.

        The fundamental quantities defining a SpatialAxis are it layer edges.
        All other quantities are derived from these edges.

        Options for specifying edges are
        1) read them from a file, specified by fname,
        2) generate them from axis specs in dict, specified by defn_dect.

        If neither of this arguments are provided, then defn_dict is set to the defaults
        returned by spatial_axis_defn_dict(axisname).

        file: assume edges variable in fname is named axis_name+"_edges"
        other fields in the input file are ignored

        dict: defn_dict is a dict required to have the following keys.
        The values are dicts with a value key whose value is used.
        E.g. defn_dict["units"]["value"] = "m".
        The function spatial_axis_defn_dict returns a dict with these required keys:
            axisname (str): name of axis
            units (str): units of axis values
            nlevs (int): number of layers
            edge_start (float): first edge value
            edge_end (float): last edge value
            delta_ratio_max (float): maximum ratio of layer thicknesses
        """

        if fname is not None:
            if defn_dict is not None:
                raise ValueError("fname and defn_dict cannot both be provided")
            if axisname is None:
                msg = "if fname is provided then axisname must be provided also"
                raise ValueError(msg)
            self.axisname = axisname
            with Dataset(fname, mode="r") as fptr:
                fptr.set_auto_mask(False)
                self.units = fptr.variables[axisname + "_edges"].units
                self.edges = fptr.variables[axisname + "_edges"][:]
                self.defn_dict_values = getattr(fptr, "defn_dict_values", None)
        else:
            if defn_dict is not None:
                if axisname is not None:
                    raise ValueError("defn_dict and axisname cannot both be provided")
            else:
                defn_dict = spatial_axis_defn_dict(axisname)
            self.axisname = defn_dict["axisname"]["value"]
            self.units = defn_dict["units"]["value"]
            self.edges = _gen_edges(defn_dict)
            self.defn_dict_values = "\n".join(
                key + "=" + "%s" % value["value"] for key, value in defn_dict.items()
            )

        self._nlevs = len(self.edges) - 1
        self.mid = 0.5 * (self.edges[:-1] + self.edges[1:])
        self.delta = self.edges[1:] - self.edges[:-1]
        self.delta_r = 1.0 / self.delta
        self.delta_mid = np.ediff1d(self.mid)
        self.delta_mid_r = 1.0 / self.delta_mid

        self.dump_names = {
            "bounds": self.axisname + "_bounds",
            "edges": self.axisname + "_edges",
            "delta": self.axisname + "_delta",
        }

    def __len__(self):
        """length of axis, i.e., number of layers"""
        return self._nlevs

    def dump(self, fname, caller):
        """write axis information to a netCDF4 file"""

        with Dataset(fname, mode="w", format="NETCDF3_64BIT_OFFSET") as fptr:
            datestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            name = class_name(self) + ".dump"
            msg = datestamp + ": generated by " + name + " called from " + caller
            fptr.history = msg

            if self.defn_dict_values is not None:
                fptr.defn_dict_values = self.defn_dict_values

            create_dimensions_verify(fptr, self.dump_dimensions())
            create_vars(fptr, self.dump_vars_metadata())

            self.dump_write(fptr)

    def dump_dimensions(self):
        """return dictionary of dimensions for dumping self to a netCDF4 file"""

        return {
            self.axisname: len(self),
            "nbnds": 2,
            self.dump_names["edges"]: len(self) + 1,
        }

    def dump_vars_metadata(self):
        """variable metadata for dump"""
        res = {}
        res[self.axisname] = {
            "dimensions": (self.axisname,),
            "attrs": {
                "long_name": self.axisname + " layer midpoints",
                "units": self.units,
                "bounds": self.dump_names["bounds"],
            },
        }
        res[self.dump_names["bounds"]] = {
            "dimensions": (self.axisname, "nbnds"),
            "attrs": {"long_name": self.axisname + " layer bounds"},
        }
        res[self.dump_names["edges"]] = {
            "dimensions": (self.dump_names["edges"],),
            "attrs": {"long_name": self.axisname + " layer edges", "units": self.units},
        }
        res[self.dump_names["delta"]] = {
            "dimensions": (self.axisname,),
            "attrs": {
                "long_name": self.axisname + " layer thickness",
                "units": self.units,
            },
        }
        return res

    def dump_write(self, fptr):
        """write variables for dump"""

        fptr.variables[self.axisname][:] = self.mid
        fptr.variables[self.dump_names["bounds"]][:, 0] = self.edges[:-1]
        fptr.variables[self.dump_names["bounds"]][:, 1] = self.edges[1:]
        fptr.variables[self.dump_names["edges"]][:] = self.edges
        fptr.variables[self.dump_names["delta"]][:] = self.delta

    def int_vals_mid(self, vals):
        """
        integral of vals at layer midpoints
        works for multiple tracer values, assuming vertical axis is last
        """
        return (self.delta * vals).sum(axis=-1)


def _gen_edges(defn_dict):
    """generate edges from axis specs in defn_dict"""

    nlevs = defn_dict["nlevs"]["value"]

    # polynomial stretching function
    # stretch_fcn(-1)=-1, stretch_fcn'(-1)=0, stretch_fcn''(-1)=0
    # stretch_fcn(1)=1, stretch_fcn'(1)=0, stretch_fcn''(1)=0
    # the mean of stretch_fcn is 0, so adding multiples of it to the thichnesses
    # doesn't change the mean thickness
    coord = np.linspace(-1.0, 1.0, nlevs)
    stretch_fcn = 0.125 * coord * (15 + coord * coord * (3 * coord * coord - 10))

    delta_avg = (1.0 / nlevs) * (
        defn_dict["edge_end"]["value"] - defn_dict["edge_start"]["value"]
    )

    delta_ratio_max = defn_dict["delta_ratio_max"]["value"]
    if delta_ratio_max < 1.0:
        msg = "delta_ratio_max must be >= 1.0"
        raise ValueError(msg)
    # stretch_factor solves
    # (delta_avg + stretch_factor) / (delta_avg - stretch_factor) = delta_ratio_max
    stretch_factor = delta_avg * (delta_ratio_max - 1) / (delta_ratio_max + 1)

    delta = delta_avg + stretch_factor * stretch_fcn

    edges = np.empty(1 + nlevs)
    edges[0] = defn_dict["edge_start"]["value"]
    edges[1:] = defn_dict["edge_start"]["value"] + delta.cumsum()

    return edges


def spatial_axis_defn_dict(axisname="depth", trap_unknown=True, **kwargs):
    """
    return a defn_dict suitable for initializing a class object
    dict has additional attributes useful for argparse arguments
    """

    # framework for defn_dict, with no values besides axisname
    defn_dict = {
        "axisname": {"type": str, "help": "axis name", "value": axisname},
        "units": {"type": str, "help": "axis units", "value": None},
        "nlevs": {"type": int, "help": "number of layers", "value": None},
        "edge_start": {"type": float, "help": "start of edges", "value": None},
        "edge_end": {"type": float, "help": "end of edges", "value": None},
        "delta_ratio_max": {
            "type": float,
            "help": "maximum ratio of layer thicknesses",
            "value": None,
        },
    }

    # set item defaults, based on axisname argument
    if axisname == "depth":
        defn_dict["units"]["value"] = "m"
        defn_dict["nlevs"]["value"] = 30
        defn_dict["edge_start"]["value"] = 0.0
        defn_dict["edge_end"]["value"] = 900.0
        defn_dict["delta_ratio_max"]["value"] = 5.0

    # populate defn_dict with values from kwargs
    for key, value in kwargs.items():
        if key in defn_dict:
            defn_dict[key]["value"] = value
        elif trap_unknown:
            msg = "unknown key %s" % key
            raise ValueError(msg)

    # ensure items are set
    for key in defn_dict:
        if defn_dict[key]["value"] is None:
            msg = "value for key %s not set" % key
            raise ValueError(msg)

    return defn_dict
