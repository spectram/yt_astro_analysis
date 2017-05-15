import os
import sys

from yt.convenience import load
from yt.frontends.halo_catalog.data_structures import \
    HaloCatalogDataset
from yt.utilities.answer_testing.framework import \
    FieldValuesTest, \
    requires_ds

_fields = (("halos", "particle_position_x"),
           ("halos", "particle_position_y"),
           ("halos", "particle_position_z"),
           ("halos", "particle_mass"))

methods = {"fof": 2, "hop": 2, "rockstar": 3}
decimals = {"fof": 10, "hop": 10, "rockstar": 1}

etiny = "enzo_tiny_cosmology/DD0046/DD0046"
@requires_ds(etiny, big_data=True)
def test_halo_finders():
    from mpi4py import MPI
    filename = os.path.join(os.path.dirname(__file__),
                            "run_halo_finder.py")
    for method in methods:
        comm = MPI.COMM_SELF.Spawn(sys.executable,
                                   args=[filename, method],
                                   maxprocs=methods[method])
        comm.Disconnect()

        fn = os.path.join(os.path.dirname(__file__),
                          "halo_catalogs", method,
                          "%s.0.h5" % method)
        ds = load(fn)
        assert isinstance(ds, HaloCatalogDataset)
        for field in _fields:
            yield FieldValuesTest(ds, field, particle_type=True,
                                  decimals=decimals[method])
