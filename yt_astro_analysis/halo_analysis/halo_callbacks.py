"""
Halo callback object



"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

import h5py
import numpy as np

from yt.data_objects.profiles import \
     Profile1D
from yt.data_objects.yt_array import \
     YTArray, YTQuantity
from yt.funcs import \
     ensure_list
from yt.utilities.cosmology import \
     Cosmology
from yt.utilities.exceptions import YTUnitConversionError
from yt.utilities.logger import ytLogger as mylog
     
from .operator_registry import \
    callback_registry

def add_callback(name, function):
    callback_registry[name] =  HaloCallback(function)

class HaloCallback(object):
    def __init__(self, function, args=None, kwargs=None):
        self.function = function
        self.args = args
        if self.args is None: self.args = []
        self.kwargs = kwargs
        if self.kwargs is None: self.kwargs = {}

    def __call__(self, halo):
        self.function(halo, *self.args, **self.kwargs)
        return True

def halo_sphere(halo, radius_field="virial_radius", factor=1.0):
    r"""
    Create a sphere data container to associate with a halo.

    Parameters
    ----------
    halo : Halo object
        The Halo object to be provided by the HaloCatalog.
    radius_field : string
        Field to be retrieved from the quantities dictionary as 
        the basis of the halo radius.
        Default: "virial_radius".
    factor : float
        Factor to be multiplied by the base radius for defining 
        the radius of the sphere.
        Defautl: 1.0.
        
    """

    dpf = halo.halo_catalog.data_pf
    hpf = halo.halo_catalog.halos_pf
    center = dpf.arr([halo.quantities["particle_position_%s" % axis] \
                      for axis in "xyz"]) / dpf.length_unit
    radius = factor * halo.quantities[radius_field] / dpf.length_unit
    sphere = dpf.h.sphere(center, (radius, "code_length"))
    setattr(halo, "data_object", sphere)

add_callback("sphere", halo_sphere)

def profile(halo, x_field, y_fields, x_bins=32, x_range=None, x_log=True,
            weight_field="cell_mass", accumulation=False, storage="profiles"):
    r"""
    Create 1d profiles.

    Store profile data in a dictionary associated with the halo object.

    Parameters
    ----------
    halo : Halo object
        The Halo object to be provided by the HaloCatalog.
    x_field : string
        The binning field for the profile.
    y_fields : string or list of strings
        The fields to be profiled.
    x_bins : int
        The number of bins in the profile.
        Default: 32
    x_range : (float, float)
        The range of the x_field.  If None, the extrema are used.
        Default: None
    x_log : bool
        Flag for logarithmmic binning.
        Default: True
    weight_field : string
        Weight field for profiling.
        Default : "cell_mass"
    accumulation : bool
        If True, profile data is a cumulative sum.
        Default : False
    storage : string
        Name of the dictionary to store profiles.
        Default: "profiles"

    """

    mylog.info("Calculating 1D profile for halo %d." % 
               halo.quantities["particle_identifier"])
    
    dpf = halo.halo_catalog.data_pf
    
    if x_range is None:
        x_range = halo.data_object.quantities["Extrema"](x_field)[0]
        # temporary check until derived quantities are fixed
        # right now derived quantities do not work with units, so once they do, let us know
        try:
            x_range[0]._unit_repr_check_same("cm")
            raise RuntimeError("Looks like derived quantities have been fixed.  Fix this code!")
        except YTUnitConversionError:
            # for now, Extrema return dimensionless, but assume it is code_length
            x_range = [dpf.arr(x.to_ndarray(), "cm") for x in x_range]
            
    my_profile = Profile1D(halo.data_object, x_field, x_bins, 
                           x_range[0], x_range[1], x_log, 
                           weight_field=weight_field)
    my_profile.add_fields(ensure_list(y_fields))

    # temporary fix since profiles do not have units at the moment
    for field in my_profile.field_data:
        my_profile.field_data[field] = dpf.arr(my_profile[field],
                                               dpf.field_info[field].units)

    # accumulate, if necessary
    if accumulation:
        used = my_profile.used        
        for field in my_profile.field_data:
            if weight_field is None:
                my_profile.field_data[field][used] = \
                    np.cumsum(my_profile.field_data[field][used])
            else:
                my_weight = my_profile.weight[:, 0]
                my_profile.field_data[field][used] = \
                  np.cumsum(my_profile.field_data[field][used] * my_weight[used]) / \
                  np.cumsum(my_weight[used])
                  
    # create storage dictionary
    prof_store = dict([(field, my_profile[field]) \
                       for field in my_profile.field_data])
    prof_store[my_profile.x_field] = my_profile.x

    if hasattr(halo, storage):
        halo_store = getattr(halo, storage)
        if "used" in halo_store:
            halo_store["used"] &= my_profile.used
    else:
        halo_store = {"used": my_profile.used}
        setattr(halo, storage, halo_store)
    halo_store.update(prof_store)

add_callback("profile", profile)

def virial_quantities(halo, fields, critical_overdensity=200,
                      profile_storage="profiles"):
    r"""
    Calculate the value of the given fields at the virial radius defined at 
    the given critical density by interpolating from radial profiles.

    Parameters
    ----------    
    halo : Halo object
        The Halo object to be provided by the HaloCatalog.
    fields : (field, units) tuple or list of tuples
        The fields whose virial values are to be calculated.
    critical_density : float
        The value of the overdensity at which to evaulate the virial quantities.  
        Overdensity is with respect to the critical density.
        Default: 200
    profile_storage : string
        Name of the halo attribute that holds the profiles to be used.
        Default: "profiles"
    
    """

    mylog.info("Calculating virial quantities for halo %d." %
               halo.quantities["particle_identifier"])

    fields = ensure_list(fields)
    for field in fields:
        q_tuple = ("%s_%d" % (field[0], critical_overdensity), "callback")
        if q_tuple not in halo.halo_catalog.quantities:
            halo.halo_catalog.quantities.append(q_tuple)
    
    dpf = halo.halo_catalog.data_pf
    co = Cosmology(hubble_constant=dpf.hubble_constant,
                   omega_matter=dpf.omega_matter,
                   omega_lambda=dpf.omega_lambda,
                   unit_registry=dpf.unit_registry)
    profile_data = getattr(halo, profile_storage)

    if ("gas", "overdensity") not in profile_data:
      raise RuntimeError('virial_quantities callback requires profile of ("gas", "overdensity").')

    overdensity = profile_data[("gas", "overdensity")]
    dfilter = np.isfinite(overdensity) & profile_data["used"] & (overdensity > 0)
    
    vquantities = dict([("%s_%d" % (field[0], critical_overdensity), 0) \
                        for field in fields])
                        
    if dfilter.sum() < 2:
        halo.quantities.update(vquantities)
        return

    # find interpolation index
    # require a negative slope, but not monotonicity
    vod = overdensity[dfilter].to_ndarray()
    if (vod > critical_overdensity).all():
        if vod[-1] < vod[-2]:
            index = -2
        else:
            halo.quantities.update(vquantities)
            return
    elif (vod < critical_overdensity).all():
        if vod[0] > vod[1]:
            index = 0
        else:
            halo.quantities.update(vquantities)
            return            
    else:
        # take first instance of downward intersection with critical value
        index = np.where((vod[:-1] >= critical_overdensity) &
                         (vod[1:] < critical_overdensity))[0][0]

    for field in fields:
        v_prof = profile_data[field[0]][dfilter].to_ndarray()
        slope = np.log(v_prof[index + 1] / v_prof[index]) / \
          np.log(vod[index + 1] / vod[index])
        value = dpf.quan(np.exp(slope * np.log(critical_overdensity / 
                                               vod[index])) * v_prof[index],
                         profile_data[field[0]].units)
        vquantities["%s_%d" % (field[0], critical_overdensity)] = value.in_units(field[1])

    halo.quantities.update(vquantities)

add_callback("virial_quantities", virial_quantities)
