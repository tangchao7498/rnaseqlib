##
## Utilities related to Rpy2 library
##
import os
import sys
import time

import rnaseqlib
import rnaseqlib.utils as utils

try:
    import rpy2
    from rpy2.robjects import r
    import rpy2.robjects as robj
    import rpy2.robjects.numpy2ri
    from rpy2.robjects.packages import importr
    rpy2.robjects.numpy2ri.activate()
    from rpy2.robjects.lib import grid
    from rpy2.robjects import r, Formula
    py2ri_orig = rpy2.robjects.conversion.py2ri
except:
    raise Exception, "Cannot import rpy2."


def run_ma_loess(x, y):
    """
    Run MA-based loess normalization on X and Y. Computes

      M = log(X/Y)
      A = 0.5 * log(X*Y)

    Fits loess curve to M ~ A and corrects X and Y accordingly.

    Assumes input X and Y values are non-logged.
    """
    M = np.log2(x) - np.log2(y)
    # A = average intensity 1/2(XY)
    A = 0.5 * (np.log2(x * y))
    # Fit loess to M ~ A
    corrected_m, corrected_a = \
        run_loess(A, M)
    # Fit M ~ A 
    corrected_m, correction_factor = run_loess(A, M)
    corrected_x = 2**((2*A + corrected_m)/2.)
    corrected_y = 2**((2*A - corrected_m)/2.)
    return corrected_x, corrected_y


def run_loess(x, y, span=0.8):
    """
    Predict y as function of X
    """
    x = robj.FloatVector(x)
    y = robj.FloatVector(y)
    robj.globalenv["x"] = x
    robj.globalenv["y"] = y
    loess_fit = r.loess("y ~ x")
    correction_factor = np.array(list(r.predict(loess_fit, x)))
    corrected_y = \
        np.array(list(y)) - correction_factor
    return corrected_y, correction_factor
