from numbers import Integral, Real
from math import exp, erf, pi, sqrt
from collections.abc import Iterable

import h5py
import numpy as np

# Version of WMP nuclear data format
WMP_VERSION = 'v1.0'

# The value of the Boltzman constant in units of eV / K
K_BOLTZMANN = 8.6173303e-5

# Constants that determine which value to access
_MP_EA = 0       # Pole

# Residue indices
_MP_RT = 1       # Residue total
_MP_RA = 2       # Residue absorption
_MP_RF = 3       # Residue fission

# Polynomial fit indices
_FIT_T = 0       # Total
_FIT_A = 1       # Absorption
_FIT_F = 2       # Fission

ATOMIC_SYMBOL = {0: 'n', 1: 'H', 2: 'He', 3: 'Li', 4: 'Be', 5: 'B', 6: 'C',
                 7: 'N', 8: 'O', 9: 'F', 10: 'Ne', 11: 'Na', 12: 'Mg', 13: 'Al',
                 14: 'Si', 15: 'P', 16: 'S', 17: 'Cl', 18: 'Ar', 19: 'K',
                 20: 'Ca', 21: 'Sc', 22: 'Ti', 23: 'V', 24: 'Cr', 25: 'Mn',
                 26: 'Fe', 27: 'Co', 28: 'Ni', 29: 'Cu', 30: 'Zn', 31: 'Ga',
                 32: 'Ge', 33: 'As', 34: 'Se', 35: 'Br', 36: 'Kr', 37: 'Rb',
                 38: 'Sr', 39: 'Y', 40: 'Zr', 41: 'Nb', 42: 'Mo', 43: 'Tc',
                 44: 'Ru', 45: 'Rh', 46: 'Pd', 47: 'Ag', 48: 'Cd', 49: 'In',
                 50: 'Sn', 51: 'Sb', 52: 'Te', 53: 'I', 54: 'Xe', 55: 'Cs',
                 56: 'Ba', 57: 'La', 58: 'Ce', 59: 'Pr', 60: 'Nd', 61: 'Pm',
                 62: 'Sm', 63: 'Eu', 64: 'Gd', 65: 'Tb', 66: 'Dy', 67: 'Ho',
                 68: 'Er', 69: 'Tm', 70: 'Yb', 71: 'Lu', 72: 'Hf', 73: 'Ta',
                 74: 'W', 75: 'Re', 76: 'Os', 77: 'Ir', 78: 'Pt', 79: 'Au',
                 80: 'Hg', 81: 'Tl', 82: 'Pb', 83: 'Bi', 84: 'Po', 85: 'At',
                 86: 'Rn', 87: 'Fr', 88: 'Ra', 89: 'Ac', 90: 'Th', 91: 'Pa',
                 92: 'U', 93: 'Np', 94: 'Pu', 95: 'Am', 96: 'Cm', 97: 'Bk',
                 98: 'Cf', 99: 'Es', 100: 'Fm', 101: 'Md', 102: 'No',
                 103: 'Lr', 104: 'Rf', 105: 'Db', 106: 'Sg', 107: 'Bh',
                 108: 'Hs', 109: 'Mt', 110: 'Ds', 111: 'Rg', 112: 'Cn',
                 113: 'Nh', 114: 'Fl', 115: 'Mc', 116: 'Lv', 117: 'Ts',
                 118: 'Og'}
ATOMIC_NUMBER = {value: key for key, value in ATOMIC_SYMBOL.items()}

def check_type(name, value, expected_type):
    r"""Ensure that an object is of an expected type.

    Parameters
    ----------
    name : str
        Description of value being checked
    value : object
        Object to check type of
    expected_type : type or Iterable of type
        type to check object against
    """

    if not isinstance(value, expected_type):
        if isinstance(expected_type, Iterable):
            msg = 'Unable to set "{0}" to "{1}" which is not one of the ' \
                  'following types: "{2}"'.format(name, value, ', '.join(
                      [t.__name__ for t in expected_type]))
        else:
            msg = 'Unable to set "{0}" to "{1}" which is not of type "{2}"'.format(
                name, value, expected_type.__name__)
        raise TypeError(msg)

def check_value(name, value, accepted_values):
    r"""Ensure that an object's value is contained in a set of acceptable values.

    Parameters
    ----------
    name : str
        Description of value being checked
    value : collections.Iterable
        Object to check
    accepted_values : collections.Container
        Container of acceptable values

    """

    if value not in accepted_values:
        msg = 'Unable to set "{0}" to "{1}" since it is not in "{2}"'.format(
            name, value, accepted_values)
        raise ValueError(msg)

def check_greater_than(name, value, minimum, equality=False):
    r"""Ensure that an object's value is greater than a given value.

    Parameters
    ----------
    name : str
        Description of the value being checked
    value : object
        Object to check
    minimum : object
        Minimum value to check against
    equality : bool, optional
        Whether equality is allowed. Defaults to False.

    """

    if equality:
        if value < minimum:
            msg = 'Unable to set "{0}" to "{1}" since it is less than ' \
                  '"{2}"'.format(name, value, minimum)
            raise ValueError(msg)
    else:
        if value <= minimum:
            msg = 'Unable to set "{0}" to "{1}" since it is less than ' \
                  'or equal to "{2}"'.format(name, value, minimum)
            raise ValueError(msg)

def _faddeeva(z):
    r"""Evaluate the complex Faddeeva function.

    Technically, the value we want is given by the equation:

    .. math::
        w(z) = \frac{i}{\pi} \int_{-\infty}^{\infty} \frac{1}{z - t}
        \exp(-t^2) \text{d}t

    as shown in Equation 63 from Hwang, R. N. "A rigorous pole
    representation of multilevel cross sections and its practical
    applications." Nuclear Science and Engineering 96.3 (1987): 192-209.

    The :func:`scipy.special.wofz` function evaluates
    :math:`w(z) = \exp(-z^2) \text{erfc}(-iz)`. These two forms of the Faddeeva
    function are related by a transformation.

    If we call the integral form :math:`w_\text{int}`, and the function form
    :math:`w_\text{fun}`:

    .. math::
        w_\text{int}(z) =
        \begin{cases}
            w_\text{fun}(z) & \text{for } \text{Im}(z) > 0\\
            -w_\text{fun}(z^*)^* & \text{for } \text{Im}(z) < 0
        \end{cases}

    Parameters
    ----------
    z : complex
        Argument to the Faddeeva function.

    Returns
    -------
    complex
        :math:`\frac{i}{\pi} \int_{-\infty}^{\infty} \frac{1}{z - t} \exp(-t^2)
        \text{d}t`

    """
    from scipy.special import wofz
    if np.angle(z) > 0:
        return wofz(z)
    else:
        return -np.conj(wofz(z.conjugate()))


def _broaden_wmp_polynomials(E, dopp, n):
    r"""Evaluate Doppler-broadened windowed multipole curvefit.

    The curvefit is a polynomial of the form :math:`\frac{a}{E}
    + \frac{b}{\sqrt{E}} + c + d \sqrt{E} + \ldots`

    Parameters
    ----------
    E : Real
        Energy to evaluate at.
    dopp : Real
        sqrt(atomic weight ratio / kT) in units of eV.
    n : Integral
        Number of components to the polynomial.

    Returns
    -------
    numpy.ndarray
        The value of each Doppler-broadened curvefit polynomial term.

    """
    sqrtE = sqrt(E)
    beta = sqrtE * dopp
    half_inv_dopp2 = 0.5 / dopp**2
    quarter_inv_dopp4 = half_inv_dopp2**2

    if beta > 6.0:
        # Save time, ERF(6) is 1 to machine precision.
        # beta/sqrtpi*exp(-beta**2) is also approximately 1 machine epsilon.
        erf_beta = 1.0
        exp_m_beta2 = 0.0
    else:
        erf_beta = erf(beta)
        exp_m_beta2 = exp(-beta**2)

    # Assume that, for sure, we'll use a second order (1/E, 1/V, const)
    # fit, and no less.

    factors = np.zeros(n)

    factors[0] = erf_beta / E
    factors[1] = 1.0 / sqrtE
    factors[2] = (factors[0] * (half_inv_dopp2 + E)
                  + exp_m_beta2 / (beta * sqrt(pi)))

    # Perform recursive broadening of high order components. range(1, n-2)
    # replaces a do i = 1, n-3.  All indices are reduced by one due to the
    # 1-based vs. 0-based indexing.
    for i in range(1, n-2):
        if i != 1:
            factors[i+2] = (-factors[i-2] * (i - 1.0) * i * quarter_inv_dopp4
                + factors[i] * (E + (1.0 + 2.0 * i) * half_inv_dopp2))
        else:
            factors[i+2] = factors[i]*(E + (1.0 + 2.0 * i) * half_inv_dopp2)

    return factors


class WindowedMultipole(object):
    """Resonant cross sections represented in the windowed multipole format.

    Parameters
    ----------

    Attributes
    ----------
    fit_order : Integral
        Order of the windowed curvefit.
    fissionable : bool
        Whether or not the target nuclide has fission data.
    spacing : Real
        The width of each window in sqrt(E)-space.  For example, the frst window
        will end at (sqrt(start_E) + spacing)**2 and the second window at
        (sqrt(start_E) + 2*spacing)**2.
    sqrtAWR : Real
        Square root of the atomic weight ratio of the target nuclide.
    start_E : Real
        Lowest energy in eV the library is valid for.
    end_E : Real
        Highest energy in eV the library is valid for.
    data : np.ndarray
        A 2D array of complex poles and residues.  data[i, 0] gives the energy
        at which pole i is located.  data[i, 1:] gives the residues associated
        with the i-th pole.  There are 3 residues, one each for the total,
        absorption, and fission channels.
    w_start : np.ndarray
        A 1D array of Integral values.  w_start[i] - 1 is the index of the first
        pole in window i.
    w_end : np.ndarray
        A 1D array of Integral values.  w_end[i] - 1 is the index of the last
        pole in window i.
    broaden_poly : np.ndarray
        A 1D array of boolean values indicating whether or not the polynomial
        curvefit in that window should be Doppler broadened.
    curvefit : np.ndarray
        A 3D array of Real curvefit polynomial coefficients.  curvefit[i, 0, :]
        gives coefficients for the total cross section in window i.
        curvefit[i, 1, :] gives absorption coefficients and curvefit[i, 2, :]
        gives fission coefficients.  The polynomial terms are increasing powers
        of sqrt(E) starting with 1/E e.g:
        a/E + b/sqrt(E) + c + d sqrt(E) + ...

    """
    def __init__(self):
        self.spacing = None
        self.sqrtAWR = None
        self.start_E = None
        self.end_E = None
        self.data = None
        self.w_start = None
        self.w_end = None
        self.broaden_poly = None
        self.curvefit = None

    @property
    def fit_order(self):
        return self.curvefit.shape[1] - 1

    @property
    def fissionable(self):
        return self.data.shape[1] == 4

    @property
    def spacing(self):
        return self._spacing

    @property
    def sqrtAWR(self):
        return self._sqrtAWR

    @property
    def start_E(self):
        return self._start_E

    @property
    def end_E(self):
        return self._end_E

    @property
    def data(self):
        return self._data

    @property
    def l_value(self):
        return self._l_value

    @property
    def w_start(self):
        return self._w_start

    @property
    def w_end(self):
        return self._w_end

    @property
    def broaden_poly(self):
        return self._broaden_poly

    @property
    def curvefit(self):
        return self._curvefit

    @spacing.setter
    def spacing(self, spacing):
        if spacing is not None:
            check_type('spacing', spacing, Real)
            check_greater_than('spacing', spacing, 0.0, equality=False)
        self._spacing = spacing

    @sqrtAWR.setter
    def sqrtAWR(self, sqrtAWR):
        if sqrtAWR is not None:
            check_type('sqrtAWR', sqrtAWR, Real)
            check_greater_than('sqrtAWR', sqrtAWR, 0.0, equality=False)
        self._sqrtAWR = sqrtAWR

    @start_E.setter
    def start_E(self, start_E):
        if start_E is not None:
            check_type('start_E', start_E, Real)
            check_greater_than('start_E', start_E, 0.0, equality=True)
        self._start_E = start_E

    @end_E.setter
    def end_E(self, end_E):
        if end_E is not None:
            check_type('end_E', end_E, Real)
            check_greater_than('end_E', end_E, 0.0, equality=False)
        self._end_E = end_E

    @data.setter
    def data(self, data):
        if data is not None:
            check_type('data', data, np.ndarray)
            if len(data.shape) != 2:
                raise ValueError('Multipole data arrays must be 2D')
            if data.shape[1] not in (3, 4):
                raise ValueError(
                     'data.shape[1] must be 3 or 4. One value for the pole.'
                     ' One each for the total and absorption residues. '
                     'Possibly one more for a fission residue.')
            if not np.issubdtype(data.dtype, complex):
                raise TypeError('Multipole data arrays must be complex dtype')
        self._data = data

    @w_start.setter
    def w_start(self, w_start):
        if w_start is not None:
            check_type('w_start', w_start, np.ndarray)
            if len(w_start.shape) != 1:
                raise ValueError('Multipole w_start arrays must be 1D')
            if not np.issubdtype(w_start.dtype, int):
                raise TypeError('Multipole w_start arrays must be integer'
                                ' dtype')
        self._w_start = w_start

    @w_end.setter
    def w_end(self, w_end):
        if w_end is not None:
            check_type('w_end', w_end, np.ndarray)
            if len(w_end.shape) != 1:
                raise ValueError('Multipole w_end arrays must be 1D')
            if not np.issubdtype(w_end.dtype, int):
                raise TypeError('Multipole w_end arrays must be integer dtype')
        self._w_end = w_end

    @broaden_poly.setter
    def broaden_poly(self, broaden_poly):
        if broaden_poly is not None:
            check_type('broaden_poly', broaden_poly, np.ndarray)
            if len(broaden_poly.shape) != 1:
                raise ValueError('Multipole broaden_poly arrays must be 1D')
            if not np.issubdtype(broaden_poly.dtype, bool):
                raise TypeError('Multipole broaden_poly arrays must be boolean'
                                ' dtype')
        self._broaden_poly = broaden_poly

    @curvefit.setter
    def curvefit(self, curvefit):
        if curvefit is not None:
            check_type('curvefit', curvefit, np.ndarray)
            if len(curvefit.shape) != 3:
                raise ValueError('Multipole curvefit arrays must be 3D')
            if curvefit.shape[2] not in (2, 3):  # sig_t, sig_a (maybe sig_f)
                raise ValueError('The third dimension of multipole curvefit'
                                 ' arrays must have a length of 2 or 3')
            if not np.issubdtype(curvefit.dtype, float):
                raise TypeError('Multipole curvefit arrays must be float dtype')
        self._curvefit = curvefit

    @classmethod
    def from_hdf5(cls, group_or_filename):
        """Construct a WindowedMultipole object from an HDF5 group or file.

        Parameters
        ----------
        group_or_filename : h5py.Group or str
            HDF5 group containing multipole data. If given as a string, it is
            assumed to be the filename for the HDF5 file, and the first group is
            used to read from.

        Returns
        -------
        openmc.data.WindowedMultipole
            Resonant cross sections represented in the windowed multipole
            format.

        """

        if isinstance(group_or_filename, h5py.Group):
            group = group_or_filename
        else:
            h5file = h5py.File(group_or_filename, 'r')
            try:
                version = h5file['version'].value.decode()
            except AttributeError:
                version = h5file['version'].value[0].decode()
            if version != WMP_VERSION:
                raise ValueError('The given WMP data uses version '
                    + version + ' whereas your installation of the OpenMC '
                    'Python API expects version ' + WMP_VERSION)
            group = h5file['nuclide']

        out = cls()

        # Read scalars.

        out.spacing = group['spacing'].value
        out.sqrtAWR = group['sqrtAWR'].value
        out.start_E = group['start_E'].value
        out.end_E = group['end_E'].value

        # Read arrays.

        err = "WMP '{}' array shape is not consistent with the '{}' array shape"

        out.data = group['data'].value

        out.w_start = group['w_start'].value

        out.w_end = group['w_end'].value
        if out.w_end.shape[0] != out.w_start.shape[0]:
            raise ValueError(err.format('w_end', 'w_start'))

        out.broaden_poly = group['broaden_poly'].value.astype(np.bool)
        if out.broaden_poly.shape[0] != out.w_start.shape[0]:
            raise ValueError(err.format('broaden_poly', 'w_start'))

        out.curvefit = group['curvefit'].value
        if out.curvefit.shape[0] != out.w_start.shape[0]:
            raise ValueError(err.format('curvefit', 'w_start'))

        # _broaden_wmp_polynomials assumes the curve fit has at least 3 terms.
        if out.fit_order < 2:
            raise ValueError("Windowed multipole is only supported for "
                             "curvefits with 3 or more terms.")

        return out

    def _evaluate(self, E, T):
        """Compute total, absorption, and fission cross sections.

        Parameters
        ----------
        E : Real
            Energy of the incident neutron in eV.
        T : Real
            Temperature of the target in K.

        Returns
        -------
        3-tuple of Real
            Total, absorption, and fission microscopic cross sections at the
            given energy and temperature.

        """

        if E < self.start_E: return (0, 0, 0)
        if E > self.end_E: return (0, 0, 0)

        # ======================================================================
        # Bookkeeping

        # Define some frequently used variables.
        sqrtkT = sqrt(K_BOLTZMANN * T)
        sqrtE = sqrt(E)
        invE = 1.0 / E

        # Locate us.  The i_window calc omits a + 1 present in F90 because of
        # the 1-based vs. 0-based indexing.  Similarly startw needs to be
        # decreased by 1.  endw does not need to be decreased because
        # range(startw, endw) does not include endw.
        i_window = int(np.floor((sqrtE - sqrt(self.start_E)) / self.spacing))
        startw = self.w_start[i_window] - 1
        endw = self.w_end[i_window]

        # Initialize the ouptut cross sections.
        sig_t = 0.0
        sig_a = 0.0
        sig_f = 0.0

        # ======================================================================
        # Add the contribution from the curvefit polynomial.

        if sqrtkT != 0 and self.broaden_poly[i_window]:
            # Broaden the curvefit.
            dopp = self.sqrtAWR / sqrtkT
            broadened_polynomials = _broaden_wmp_polynomials(E, dopp,
                                                             self.fit_order + 1)
            for i_poly in range(self.fit_order+1):
                sig_t += (self.curvefit[i_window, i_poly, _FIT_T]
                          * broadened_polynomials[i_poly])
                sig_a += (self.curvefit[i_window, i_poly, _FIT_A]
                          * broadened_polynomials[i_poly])
                if self.fissionable:
                    sig_f += (self.curvefit[i_window, i_poly, _FIT_F]
                              * broadened_polynomials[i_poly])
        else:
            temp = invE
            for i_poly in range(self.fit_order+1):
                sig_t += self.curvefit[i_window, i_poly, _FIT_T] * temp
                sig_a += self.curvefit[i_window, i_poly, _FIT_A] * temp
                if self.fissionable:
                    sig_f += self.curvefit[i_window, i_poly, _FIT_F] * temp
                temp *= sqrtE

        # ======================================================================
        # Add the contribution from the poles in this window.

        if sqrtkT == 0.0:
            # If at 0K, use asymptotic form.
            for i_pole in range(startw, endw):
                psi_chi = -1j / (self.data[i_pole, _MP_EA] - sqrtE)
                c_temp = psi_chi / E
                sig_t += (self.data[i_pole, _MP_RT] * c_temp).real
                sig_a += (self.data[i_pole, _MP_RA] * c_temp).real
                if self.fissionable:
                    sig_f += (self.data[i_pole, _MP_RF] * c_temp).real

        else:
            # At temperature, use Faddeeva function-based form.
            dopp = self.sqrtAWR / sqrtkT
            for i_pole in range(startw, endw):
                Z = (sqrtE - self.data[i_pole, _MP_EA]) * dopp
                w_val = _faddeeva(Z) * dopp * invE * sqrt(pi)
                sig_t += (self.data[i_pole, _MP_RT] * w_val).real
                sig_a += (self.data[i_pole, _MP_RA] * w_val).real
                if self.fissionable:
                    sig_f += (self.data[i_pole, _MP_RF] * w_val).real

        return sig_t, sig_a, sig_f

    def __call__(self, E, T):
        """Compute total, absorption, and fission cross sections.

        Parameters
        ----------
        E : Real or Iterable of Real
            Energy of the incident neutron in eV.
        T : Real
            Temperature of the target in K.

        Returns
        -------
        3-tuple of Real or 3-tuple of numpy.ndarray
            Total, absorption, and fission microscopic cross sections at the
            given energy and temperature.

        """

        fun = np.vectorize(lambda x: self._evaluate(x, T))
        return fun(E)

    def export_to_hdf5(self, path, libver='earliest'):
        """Export windowed multipole data to an HDF5 file.

        Parameters
        ----------
        path : str
            Path to write HDF5 file to
        libver : {'earliest', 'latest'}
            Compatibility mode for the HDF5 file. 'latest' will produce files
            that are less backwards compatible but have performance benefits.

        """

        # Open file and write version.
        with h5py.File(path, 'w', libver=libver) as f:
            f.create_dataset('version', (1, ), dtype='S10')
            f['version'][:] = WMP_VERSION.encode('ASCII')

            # Make a nuclide group.
            g = f.create_group('nuclide')

            # Write scalars.
            g.create_dataset('spacing', data=np.array(self.spacing))
            g.create_dataset('sqrtAWR', data=np.array(self.sqrtAWR))
            g.create_dataset('start_E', data=np.array(self.start_E))
            g.create_dataset('end_E', data=np.array(self.end_E))

            # Write arrays.
            g.create_dataset('data', data=self.data)
            g.create_dataset('w_start', data=self.w_start)
            g.create_dataset('w_end', data=self.w_end)
            g.create_dataset('broaden_poly',
                             data=self.broaden_poly.astype(np.int8))
            g.create_dataset('curvefit', data=self.curvefit)
