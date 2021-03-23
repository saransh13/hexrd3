import numpy as np
import warnings
from hexrd.imageutil import snip1d
from hexrd.crystallography import PlaneData
from hexrd.material import Material
from hexrd.valunits import valWUnit
from hexrd import spacegroup as SG
from hexrd import symmetry, symbols, constants
from hexrd import FPA
import lmfit
import matplotlib.pyplot as plt
from scipy.interpolate import CubicSpline, interp1d
from scipy import signal
from hexrd.valunits import valWUnit
import yaml
from os import path
import pickle
import time
import h5py
from pathlib import Path

class Parameters:
    ''' ======================================================================================================== 
    ======================================================================================================== 

    >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    >> @DATE:       05/18/2020 SS 1.0 original
    >> @DETAILS:    this is the parameter class which handles all refinement parameters
        for both the Rietveld and the LeBail refimentment problems

        ======================================================================================================== 
        ======================================================================================================== 
    '''
    def __init__(self, name=None, vary=False, value=0.0, lb=-np.Inf, ub=np.Inf):

        self.param_dict = {}

        if(name is not None):
            self.add(name=name, vary=vary, value=value, lb=min, ub=max)

    def add(self, name, vary=False, value=0.0, lb=-np.Inf, ub=np.Inf):
        '''
            >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
            >> @DATE:       05/18/2020 SS 1.0 original
            >> @DETAILS:    add a single named parameter
        '''
        self[name] = Parameter(name=name, vary=vary, value=value, lb=lb, ub=ub)

    def add_many(self, names, varies, values, lbs, ubs):
        '''
            >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
            >> @DATE:       05/18/2020 SS 1.0 original
            >> @DETAILS:    load a list of named parameters 
        '''
        assert len(names)==len(varies),"lengths of tuples not consistent"
        assert len(names)==len(values),"lengths of tuples not consistent"
        assert len(names)==len(lbs),"lengths of tuples not consistent"
        assert len(names)==len(ubs),"lengths of tuples not consistent"

        for i,n in enumerate(names):
            self.add(n, vary=varies[i], value=values[i], lb=lbs[i], ub=ubs[i])

    def load(self, fname):
        '''
            >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
            >> @DATE:       05/18/2020 SS 1.0 original
            >> @DETAILS:    load parameters from yaml file
        '''
        with open(fname) as file:
            dic = yaml.load(file, Loader=yaml.FullLoader)

        for k in dic.keys():
            v = dic[k]
            self.add(k, value=np.float(v[0]), lb=np.float(v[1]),\
                     ub=np.float(v[2]), vary=np.bool(v[3]))

    def dump(self, fname):
        '''
            >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
            >> @DATE:       05/18/2020 SS 1.0 original
            >> @DETAILS:    dump the class to a yaml looking file. name is the key and the list
                            has [value, lb, ub, vary] in that order
        '''
        dic = {}
        for k in self.param_dict.keys():
            dic[k] =  [self[k].value,self[k].lb,self[k].ub,self[k].vary]

        with open(fname, 'w') as f:
            data = yaml.dump(dic, f, sort_keys=False)

    # def pretty_print(self):
    #   '''
    #       >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    #       >> @DATE:       05/18/2020 SS 1.0 original
    #       >> @DETAILS:    print to the Parameter class to the terminal
    #   '''
    #   pass

    def __getitem__(self, key):
        if(key in self.param_dict.keys()):
            return self.param_dict[key]
        else:
            raise ValueError('variable with name not found')

    def __setitem__(self, key, parm_cls):

        if(key in self.param_dict.keys()):
            warnings.warn('variable already in parameter list. overwriting ...')
        if(isinstance(parm_cls, Parameter)):
            self.param_dict[key] = parm_cls
        else:
            raise ValueError('input not a Parameter class')

    def __iter__(self):
        self.n = 0
        return self

    def __next__(self):
        if(self.n < len(self.param_dict.keys())):
            res = list(self.param_dict.keys())[self.n]
            self.n += 1
            return res
        else:
            raise StopIteration


    def __str__(self):
        retstr = 'Parameters{\n'
        for k in self.param_dict.keys():
            retstr += self[k].__str__()+'\n'

        retstr += '}'
        return retstr

class Parameter:
    ''' ======================================================================================================== 
    ======================================================================================================== 

    >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    >> @DATE:       05/18/2020 SS 1.0 original
    >> @DETAILS:    the parameters class (previous one) is a collection of this
                    parameter class indexed by the name of each variable

        ======================================================================================================== 
        ======================================================================================================== 
    '''

    def __init__(self, name=None, vary=False, value=0.0, lb=-np.Inf, ub=np.Inf):

        self.name = name
        self.vary = vary
        self.value = value
        self.lb = lb
        self.ub = ub

    def __str__(self):
        retstr =  '< Parameter \''+self.name+'\'; value : '+ \
        str(self.value)+'; bounds : ['+str(self.lb)+','+ \
        str(self.ub)+' ]; vary :'+str(self.vary)+' >'

        return retstr

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        if(isinstance(name, str)):
            self._name = name

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, val):
        self._value = val

    @property
    def min(self):
        return self._min

    @min.setter
    def min(self, minval):
        self._min = minval

    @property
    def max(self):
        return self._max

    @max.setter
    def max(self, maxval):
        self._max = maxval

    @property
    def vary(self):
        return self._vary

    @vary.setter
    def vary(self, vary):
        if(isinstance(vary, bool)):
            self._vary = vary
    
class Spectrum:
    ''' ======================================================================================================== 
    ======================================================================================================== 

    >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    >> @DATE:       05/18/2020 SS 1.0 original
    >> @DETAILS:    spectrum class holds the a pair of x,y data, in this case, would be 
                    2theta-intensity values

        ======================================================================================================== 
        ======================================================================================================== 
    '''
    def __init__(self, x=None, y=None, name=''):
        if x is None:
            self._x = np.linspace(10., 100., 500)
        else:
            self._x = x
        if y is None:
            self._y = np.log(self._x ** 2) - (self._x * 0.2) ** 2
        else:
            self._y = y
        self.name = name
        self.offset = 0
        self._scaling = 1
        self.smoothing = 0
        self.bkg_Spectrum = None

    @staticmethod
    def from_file(filename, skip_rows=0):
        try:
            if filename.endswith('.chi'):
                skip_rows = 4
            data = np.loadtxt(filename, skiprows=skip_rows)
            x = data.T[0]
            y = data.T[1]
            name = path.basename(filename).split('.')[:-1][0]
            return Spectrum(x, y, name)

        except ValueError:
            print('Wrong data format for spectrum file! - ' + filename)
            return -1

    def save(self, filename, header=''):
        data = np.dstack((self._x, self._y))
        np.savetxt(filename, data[0], header=header)

    def set_background(self, Spectrum):
        self.bkg_spectrum = Spectrum

    def reset_background(self):
        self.bkg_Spectrum = None

    def set_smoothing(self, amount):
        self.smoothing = amount

    def rebin(self, bin_size):
        """
        Returns a new Spectrum which is a rebinned version of the current one.
        """
        x, y = self.data
        x_min = np.round(np.min(x) / bin_size) * bin_size
        x_max = np.round(np.max(x) / bin_size) * bin_size
        new_x = np.arange(x_min, x_max + 0.1 * bin_size, bin_size)

        bins = np.hstack((x_min - bin_size * 0.5, new_x + bin_size * 0.5))
        new_y = (np.histogram(x, bins, weights=y)[0] / np.histogram(x, bins)[0])

        return Spectrum(new_x, new_y)

    @property
    def data(self):
        if self.bkg_Spectrum is not None:
            # create background function
            x_bkg, y_bkg = self.bkg_Spectrum.data

            if not np.array_equal(x_bkg, self._x):
                # the background will be interpolated
                f_bkg = interp1d(x_bkg, y_bkg, kind='linear')

                # find overlapping x and y values:
                ind = np.where((self._x <= np.max(x_bkg)) & (self._x >= np.min(x_bkg)))
                x = self._x[ind]
                y = self._y[ind]

                if len(x) == 0:
                    # if there is no overlapping between background and Spectrum, raise an error
                    raise BkgNotInRangeError(self.name)

                y = y * self._scaling + self.offset - f_bkg(x)
            else:
                # if Spectrum and bkg have the same x basis we just delete y-y_bkg
                x, y = self._x, self._y * self._scaling + self.offset - y_bkg
        else:
            x, y = self.original_data

        if self.smoothing > 0:
            y = gaussian_filter1d(y, self.smoothing)
        return x, y

    @data.setter
    def data(self, data):
        (x, y) = data
        self._x = x
        self._y = y
        self.scaling = 1
        self.offset = 0

    @property
    def original_data(self):
        return self._x, self._y * self._scaling + self.offset

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, new_value):
        self._x = new_value

    @property
    def y(self):
        return self._y

    @y.setter
    def y(self, new_y):
        self._y = new_y

    @property
    def scaling(self):
        return self._scaling

    @scaling.setter
    def scaling(self, value):
        if value < 0:
            self._scaling = 0
        else:
            self._scaling = value

    def limit(self, x_min, x_max):
        x, y = self.data
        return Spectrum(x[np.where((x_min < x) & (x < x_max))],
                       y[np.where((x_min < x) & (x < x_max))])

    def extend_to(self, x_value, y_value):
        """
        Extends the current Spectrum to a specific x_value by filling it with the y_value. Does not modify inplace but
        returns a new filled Spectrum
        :param x_value: Point to which extend the Spectrum should be smaller than the lowest x-value in the Spectrum or
                        vice versa
        :param y_value: number to fill the Spectrum with
        :return: extended Spectrum
        """
        x_step = np.mean(np.diff(self.x))
        x_min = np.min(self.x)
        x_max = np.max(self.x)
        if x_value < x_min:
            x_fill = np.arange(x_min - x_step, x_value-x_step*0.5, -x_step)[::-1]
            y_fill = np.zeros(x_fill.shape)
            y_fill.fill(y_value)

            new_x = np.concatenate((x_fill, self.x))
            new_y = np.concatenate((y_fill, self.y))
        elif x_value > x_max:
            x_fill = np.arange(x_max + x_step, x_value+x_step*0.5, x_step)
            y_fill = np.zeros(x_fill.shape)
            y_fill.fill(y_value)

            new_x = np.concatenate((self.x, x_fill))
            new_y = np.concatenate((self.y, y_fill))
        else:
            return self

        return Spectrum(new_x, new_y)

    def plot(self, show=False, *args, **kwargs):
        plt.plot(self.x, self.y, *args, **kwargs)
        if show:
            plt.show()

    # Operators:
    def __sub__(self, other):
        orig_x, orig_y = self.data
        other_x, other_y = other.data

        if orig_x.shape != other_x.shape:
            # todo different shape subtraction of spectra seems the fail somehow...
            # the background will be interpolated
            other_fcn = interp1d(other_x, other_x, kind='linear')

            # find overlapping x and y values:
            ind = np.where((orig_x <= np.max(other_x)) & (orig_x >= np.min(other_x)))
            x = orig_x[ind]
            y = orig_y[ind]

            if len(x) == 0:
                # if there is no overlapping between background and Spectrum, raise an error
                raise BkgNotInRangeError(self.name)
            return Spectrum(x, y - other_fcn(x))
        else:
            return Spectrum(orig_x, orig_y - other_y)

    def __add__(self, other):
        orig_x, orig_y = self.data
        other_x, other_y = other.data

        if orig_x.shape != other_x.shape:
            # the background will be interpolated
            other_fcn = interp1d(other_x, other_x, kind='linear')

            # find overlapping x and y values:
            ind = np.where((orig_x <= np.max(other_x)) & (orig_x >= np.min(other_x)))
            x = orig_x[ind]
            y = orig_y[ind]

            if len(x) == 0:
                # if there is no overlapping between background and Spectrum, raise an error
                raise BkgNotInRangeError(self.name)
            return Spectrum(x, y + other_fcn(x))
        else:
            return Spectrum(orig_x, orig_y + other_y)

    def __rmul__(self, other):
        orig_x, orig_y = self.data
        return Spectrum(np.copy(orig_x), np.copy(orig_y) * other)

    def __eq__(self, other):
        if not isinstance(other, Spectrum):
            return False
        if np.array_equal(self.data, other.data):
            return True
        return False

class Material_LeBail:

    def __init__(self, fhdf, xtal, dmin):

        self.dmin = dmin.value
        self._readHDF(fhdf, xtal)
        self._calcrmt()

        _, self.SYM_PG_d, self.SYM_PG_d_laue, self.centrosymmetric, self.symmorphic = \
        symmetry.GenerateSGSym(self.sgnum, self.sgsetting)
        self.latticeType = symmetry.latticeType(self.sgnum)
        self.sg_hmsymbol = symbols.pstr_spacegroup[self.sgnum-1].strip()
        self.GenerateRecipPGSym()
        self.CalcMaxGIndex()
        self._calchkls()

    def _readHDF(self, fhdf, xtal):

        # fexist = path.exists(fhdf)
        # if(fexist):
        fid = h5py.File(fhdf, 'r')
        xtal = "/"+xtal
        if xtal not in fid:
            raise IOError('crystal doesn''t exist in material file.')
        # else:
        #   raise IOError('material file does not exist.')

        gid         = fid.get(xtal)

        self.sgnum       = np.asscalar(np.array(gid.get('SpaceGroupNumber'), \
                                     dtype = np.int32))
        self.sgsetting = np.asscalar(np.array(gid.get('SpaceGroupSetting'), \
                                        dtype = np.int32))
        self.sgsetting -= 1
        """ 
            IMPORTANT NOTE:
            note that the latice parameters in EMsoft is nm by default
            hexrd on the other hand uses A as the default units, so we
            need to be careful and convert it right here, so there is no
            confusion later on
        """
        self.lparms      = list(gid.get('LatticeParameters'))
        fid.close()

    def _calcrmt(self):

        a = self.lparms[0]
        b = self.lparms[1]
        c = self.lparms[2]

        alpha = np.radians(self.lparms[3])
        beta  = np.radians(self.lparms[4])
        gamma = np.radians(self.lparms[5])

        ca = np.cos(alpha);
        cb = np.cos(beta);
        cg = np.cos(gamma);
        sa = np.sin(alpha);
        sb = np.sin(beta);
        sg = np.sin(gamma);
        tg = np.tan(gamma);

        '''
            direct metric tensor
        '''
        self.dmt = np.array([[a**2, a*b*cg, a*c*cb],\
                             [a*b*cg, b**2, b*c*ca],\
                             [a*c*cb, b*c*ca, c**2]])
        self.vol = np.sqrt(np.linalg.det(self.dmt))

        if(self.vol < 1e-5):
            warnings.warn('unitcell volume is suspiciously small')

        '''
            reciprocal metric tensor
        '''
        self.rmt = np.linalg.inv(self.dmt)

    def _calchkls(self):
        self.hkls = self.getHKLs(self.dmin)

    ''' calculate dot product of two vectors in any space 'd' 'r' or 'c' '''
    def CalcLength(self, u, space):

        if(space =='d'):
            vlen = np.sqrt(np.dot(u, np.dot(self.dmt, u)))
        elif(space =='r'):
            vlen = np.sqrt(np.dot(u, np.dot(self.rmt, u)))
        elif(spec =='c'):
            vlen = np.linalg.norm(u)
        else:
            raise ValueError('incorrect space argument')

        return vlen

    def getTTh(self, wavelength):

        tth = []
        for g in self.hkls:
            glen = self.CalcLength(g,'r')
            sth = glen*wavelength/2.
            if(np.abs(sth) <= 1.0):
                t = 2. * np.degrees(np.arcsin(sth))
                tth.append(t)

        tth = np.array(tth)
        return tth

    def GenerateRecipPGSym(self):

        self.SYM_PG_r = self.SYM_PG_d[0,:,:]
        self.SYM_PG_r = np.broadcast_to(self.SYM_PG_r,[1,3,3])
        self.SYM_PG_r_laue = self.SYM_PG_d[0,:,:]
        self.SYM_PG_r_laue = np.broadcast_to(self.SYM_PG_r_laue,[1,3,3])

        for i in range(1,self.SYM_PG_d.shape[0]):
            g = self.SYM_PG_d[i,:,:]
            g = np.dot(self.dmt, np.dot(g, self.rmt))
            g = np.round(np.broadcast_to(g,[1,3,3]))
            self.SYM_PG_r = np.concatenate((self.SYM_PG_r,g))

        for i in range(1,self.SYM_PG_d_laue.shape[0]):
            g = self.SYM_PG_d_laue[i,:,:]
            g = np.dot(self.dmt, np.dot(g, self.rmt))
            g = np.round(np.broadcast_to(g,[1,3,3]))
            self.SYM_PG_r_laue = np.concatenate((self.SYM_PG_r_laue,g))

        self.SYM_PG_r = self.SYM_PG_r.astype(np.int32)
        self.SYM_PG_r_laue = self.SYM_PG_r_laue.astype(np.int32)

    def CalcMaxGIndex(self):
        self.ih = 1
        while (1.0 / self.CalcLength(np.array([self.ih, 0, 0], dtype=np.float64), 'r') > self.dmin):
            self.ih = self.ih + 1
        self.ik = 1
        while (1.0 / self.CalcLength(np.array([0, self.ik, 0], dtype=np.float64), 'r') > self.dmin):
            self.ik = self.ik + 1
        self.il = 1
        while (1.0 / self.CalcLength(np.array([0, 0, self.il], dtype=np.float64),'r') > self.dmin):
            self.il = self.il + 1

    def CalcStar(self,v,space,applyLaue=False):
        '''
        this function calculates the symmetrically equivalent hkls (or uvws)
        for the reciprocal (or direct) point group symmetry.
        '''
        if(space == 'd'):
            if(applyLaue):
                sym = self.SYM_PG_d_laue
            else:
                sym = self.SYM_PG_d
        elif(space == 'r'):
            if(applyLaue):
                sym = self.SYM_PG_r_laue
            else:
                sym = self.SYM_PG_r
        else:
            raise ValueError('CalcStar: unrecognized space.')
        vsym = np.atleast_2d(v)
        for s in sym:
            vp = np.dot(s,v)
            # check if this is new
            isnew = True
            for vec in vsym:
                if(np.sum(np.abs(vp - vec)) < 1E-4):
                    isnew = False
                    break
            if(isnew):
                vsym = np.vstack((vsym, vp))
        return vsym

    def Allowed_HKLs(self, hkllist):
        '''
        this function checks if a particular g vector is allowed
        by lattice centering, screw axis or glide plane
        '''
        hkllist = np.atleast_2d(hkllist)
        centering = self.sg_hmsymbol[0]
        if(centering == 'P'):
            # all reflections are allowed
            mask = np.ones([hkllist.shape[0],],dtype=np.bool)
        elif(centering == 'F'):
            # same parity
            seo = np.sum(np.mod(hkllist+100,2),axis=1)
            mask = np.logical_not(np.logical_or(seo==1, seo==2))
        elif(centering == 'I'):
            # sum is even
            seo = np.mod(np.sum(hkllist,axis=1)+100,2)
            mask = (seo == 0)
            
        elif(centering == 'A'):
            # k+l is even
            seo = np.mod(np.sum(hkllist[:,1:3],axis=1)+100,2)
            mask = seo == 0
        elif(centering == 'B'):
            # h+l is even
            seo = np.mod(hkllist[:,0]+hkllist[:,2]+100,2)
            mask = seo == 0
        elif(centering == 'C'):
            # h+k is even
            seo = np.mod(hkllist[:,0]+hkllist[:,1]+100,2)
            mask = seo == 0
        elif(centering == 'R'):
            # -h+k+l is divisible by 3
            seo = np.mod(-hkllist[:,0]+hkllist[:,1]+hkllist[:,2]+90,3)
            mask = seo == 0
        else:
            raise RuntimeError('IsGAllowed: unknown lattice centering encountered.')
        hkls = hkllist[mask,:]

        if(not self.symmorphic):
            hkls = self.NonSymmorphicAbsences(hkls)
        return hkls.astype(np.int32)

    def omitscrewaxisabsences(self, hkllist, ax, iax):
        '''
        this function encodes the table on pg 48 of 
        international table of crystallography vol A
        the systematic absences due to different screw 
        axis is encoded here. 
        iax encodes the primary, secondary or tertiary axis
        iax == 0 : primary
        iax == 1 : secondary
        iax == 2 : tertiary
        @NOTE: only unique b axis in monoclinic systems 
        implemented as thats the standard setting
        '''
        if(self.latticeType == 'triclinic'):
            '''
                no systematic absences for the triclinic crystals
            '''
            pass
        elif(self.latticeType == 'monoclinic'):
            if(ax is not '2_1'):
                raise RuntimeError('omitscrewaxisabsences: monoclinic systems can only have 2_1 screw axis')
            '''
                only unique b-axis will be encoded
                it is the users responsibility to input 
                lattice parameters in the standard setting
                with b-axis having the 2-fold symmetry
            '''
            if(iax == 1):
                mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,2] == 0)
                mask2 = np.mod(hkllist[:,1]+100,2) != 0
                mask  = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            else:
                raise RuntimeError('omitscrewaxisabsences: only b-axis can have 2_1 screw axis')
        elif(self.latticeType == 'orthorhombic'):
            if(ax is not '2_1'):
                raise RuntimeError('omitscrewaxisabsences: orthorhombic systems can only have 2_1 screw axis')
            '''
            2_1 screw on primary axis
            h00 ; h = 2n
            '''
            if(iax == 0):
                mask1 = np.logical_and(hkllist[:,1] == 0,hkllist[:,2] == 0)
                mask2 = np.mod(hkllist[:,0]+100,2) != 0
                mask  = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(iax == 1):
                mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,2] == 0)
                mask2 = np.mod(hkllist[:,1]+100,2) != 0
                mask  = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(iax == 2):
                mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,1] == 0)
                mask2 = np.mod(hkllist[:,2]+100,2) != 0
                mask  = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
        elif(self.latticeType == 'tetragonal'):
            if(iax == 0):
                mask1 = np.logical_and(hkllist[:,0] == 0, hkllist[:,1] == 0)
                if(ax == '4_2'):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(ax in ['4_1','4_3']):
                    mask2 = np.mod(hkllist[:,2]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(iax == 1):
                mask1 = np.logical_and(hkllist[:,1] == 0, hkllist[:,2] == 0)
                mask2 = np.logical_and(hkllist[:,0] == 0, hkllist[:,2] == 0)
                if(ax == '2_1'):
                    mask3 = np.mod(hkllist[:,0]+100,2) != 0
                    mask4 = np.mod(hkllist[:,1]+100,2) != 0
                mask1 = np.logical_not(np.logical_and(mask1,mask3))
                mask2 = np.logical_not(np.logical_and(mask2,mask4))
                mask = ~np.logical_or(~mask1,~mask2)
                hkllist = hkllist[mask,:]
        elif(self.latticeType == 'trigonal'):
            mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,1] == 0)
            if(iax == 0):
                if(ax in ['3_1', '3_2']):
                    mask2 = np.mod(hkllist[:,2]+90,3) != 0
            else:
                raise RuntimeError('omitscrewaxisabsences: trigonal systems can only have screw axis')
            mask  = np.logical_not(np.logical_and(mask1,mask2))
            hkllist = hkllist[mask,:]
        elif(self.latticeType == 'hexagonal'):
            mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,1] == 0)
            if(iax == 0):
                if(ax is '6_3'):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(ax in['3_1','3_2','6_2','6_4']):
                    mask2 = np.mod(hkllist[:,2]+90,3) != 0
                elif(ax in ['6_1','6_5']):
                    mask2 = np.mod(hkllist[:,2]+120,6) != 0
            else:
                raise RuntimeError('omitscrewaxisabsences: hexagonal systems can only have screw axis')
            mask  = np.logical_not(np.logical_and(mask1,mask2))
            hkllist = hkllist[mask,:]
        elif(self.latticeType == 'cubic'):
            mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,1] == 0)
            mask2 = np.logical_and(hkllist[:,0] == 0,hkllist[:,2] == 0)
            mask3 = np.logical_and(hkllist[:,1] == 0,hkllist[:,2] == 0)
            if(ax in ['2_1','4_2']):
                mask4 = np.mod(hkllist[:,2]+100,2) != 0
                mask5 = np.mod(hkllist[:,1]+100,2) != 0
                mask6 = np.mod(hkllist[:,0]+100,2) != 0
            elif(ax in ['4_1','4_3']):
                mask4 = np.mod(hkllist[:,2]+100,4) != 0
                mask5 = np.mod(hkllist[:,1]+100,4) != 0
                mask6 = np.mod(hkllist[:,0]+100,4) != 0
            mask1 = np.logical_not(np.logical_and(mask1,mask4))
            mask2 = np.logical_not(np.logical_and(mask2,mask5))
            mask3 = np.logical_not(np.logical_and(mask3,mask6))
            mask = ~np.logical_or(~mask1,np.logical_or(~mask2,~mask3))
            hkllist = hkllist[mask,:]
        return hkllist.astype(np.int32)

    def omitglideplaneabsences(self, hkllist, plane, ip):
        '''
        this function encodes the table on pg 47 of 
        international table of crystallography vol A
        the systematic absences due to different glide 
        planes is encoded here. 
        ip encodes the primary, secondary or tertiary plane normal
        ip == 0 : primary
        ip == 1 : secondary
        ip == 2 : tertiary
        @NOTE: only unique b axis in monoclinic systems 
        implemented as thats the standard setting
        '''
        if(self.latticeType == 'triclinic'):
            pass
        elif(self.latticeType == 'monoclinic'):
            if(ip == 1):
                mask1 = hkllist[:,1] == 0
                if(plane == 'c'):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(plane == 'a'):
                    mask2 = np.mod(hkllist[:,0]+100,2) != 0
                elif(plane == 'n'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,2]+100,2) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
        elif(self.latticeType == 'orthorhombic'):
            if(ip == 0):
                mask1 = hkllist[:,0] == 0
                if(plane == 'b'):
                    mask2 = np.mod(hkllist[:,1]+100,2) != 0
                elif(plane == 'c'):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(plane == 'n'):
                    mask2 = np.mod(hkllist[:,1]+hkllist[:,2]+100,2) != 0
                elif(plane == 'd'):
                    mask2 = np.mod(hkllist[:,1]+hkllist[:,2]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(ip == 1):
                mask1 = hkllist[:,1] == 0
                if(plane == 'c'):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(plane == 'a'):
                    mask2 = np.mod(hkllist[:,0]+100,2) != 0
                elif(plane == 'n'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,2]+100,2) != 0
                elif(plane == 'd'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,2]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(ip == 2):
                mask1 = hkllist[:,2] == 0
                if(plane == 'a'):
                    mask2 = np.mod(hkllist[:,0]+100,2) != 0
                elif(plane == 'b'):
                    mask2 = np.mod(hkllist[:,1]+100,2) != 0
                elif(plane == 'n'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,1]+100,2) != 0
                elif(plane == 'd'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,1]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
        elif(self.latticeType == 'tetragonal'):
            if(ip == 0):
                mask1 = hkllist[:,2] == 0
                if(plane == 'a'):
                    mask2 = np.mod(hkllist[:,0]+100,2) != 0
                elif(plane == 'b'):
                    mask2 = np.mod(hkllist[:,1]+100,2) != 0
                elif(plane == 'n'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,1]+100,2) != 0
                elif(plane == 'd'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,1]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(ip == 1):
                mask1 = hkllist[:,0] == 0
                mask2 = hkllist[:,1] == 0
                if(plane in ['a','b']):
                    mask3 = np.mod(hkllist[:,1]+100,2) != 0
                    mask4 = np.mod(hkllist[:,0]+100,2) != 0
                elif(plane == 'c'):
                    mask3 = np.mod(hkllist[:,2]+100,2) != 0
                    mask4 = mask3
                elif(plane == 'n'):
                    mask3 = np.mod(hkllist[:,1]+hkllist[:,2]+100,2) != 0
                    mask4 = np.mod(hkllist[:,0]+hkllist[:,2]+100,2) != 0
                elif(plane == 'd'):
                    mask3 = np.mod(hkllist[:,1]+hkllist[:,2]+100,4) != 0
                    mask4 = np.mod(hkllist[:,0]+hkllist[:,2]+100,4) != 0
                mask1 = np.logical_not(np.logical_and(mask1,mask3))
                mask2 = np.logical_not(np.logical_and(mask2,mask4))
                mask = ~np.logical_or(~mask1,~mask2)
                hkllist = hkllist[mask,:]
            elif(ip == 2):
                mask1 = np.abs(hkllist[:,0]) == np.abs(hkllist[:,1])
                if(plane in ['c','n']):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(plane == 'd'):
                    mask2 = np.mod(2*hkllist[:,0]+hkllist[:,2]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
        elif(self.latticeType == 'trigonal'):
            if(plane is not 'c'):
                raise RuntimeError('omitglideplaneabsences: only c-glide allowed for trigonal systems')
            
            if(ip == 1):
                mask1 = hkllist[:,0] == 0
                mask2 = hkllist[:,1] == 0
                mask3 = hkllist[:,0] == -hkllist[:,1]
                if(plane == 'c'):
                    mask4 = np.mod(hkllist[:,2]+100,2) != 0
                else:
                    raise RuntimeError('omitglideplaneabsences: only c-glide allowed for trigonal systems')
            elif(ip == 2):
                mask1 = hkllist[:,1] == hkllist[:,0]
                mask2 = hkllist[:,0] == -2*hkllist[:,1]
                mask3 = -2*hkllist[:,0] == hkllist[:,1]
                if(plane == 'c'):
                    mask4 = np.mod(hkllist[:,2]+100,2) != 0
                else:
                    raise RuntimeError('omitglideplaneabsences: only c-glide allowed for trigonal systems')
            mask1 = np.logical_and(mask1,mask4)
            mask2 = np.logical_and(mask2,mask4)
            mask3 = np.logical_and(mask3,mask4)
            mask = np.logical_not(np.logical_or(mask1,np.logical_or(mask2,mask3)))
            hkllist = hkllist[mask,:]
        elif(self.latticeType == 'hexagonal'):
            if(plane is not 'c'):
                raise RuntimeError('omitglideplaneabsences: only c-glide allowed for hexagonal systems')
            if(ip == 2):
                mask1 = hkllist[:,0] == hkllist[:,1]
                mask2 = hkllist[:,0] == -2*hkllist[:,1]
                mask3 = -2*hkllist[:,0] == hkllist[:,1]
                mask4 = np.mod(hkllist[:,2]+100,2) != 0
                mask1 = np.logical_and(mask1,mask4)
                mask2 = np.logical_and(mask2,mask4)
                mask3 = np.logical_and(mask3,mask4)
                mask = np.logical_not(np.logical_or(mask1,np.logical_or(mask2,mask3)))
            elif(ip == 1):
                mask1 = hkllist[:,1] == 0
                mask2 = hkllist[:,0] == 0
                mask3 = hkllist[:,1] == -hkllist[:,0]
                mask4 = np.mod(hkllist[:,2]+100,2) != 0
            mask1 = np.logical_and(mask1,mask4)
            mask2 = np.logical_and(mask2,mask4)
            mask3 = np.logical_and(mask3,mask4)
            mask = np.logical_not(np.logical_or(mask1,np.logical_or(mask2,mask3)))
            hkllist = hkllist[mask,:]
        elif(self.latticeType == 'cubic'):
            if(ip == 0):
                mask1 = hkllist[:,0] == 0
                mask2 = hkllist[:,1] == 0
                mask3 = hkllist[:,2] == 0
                mask4 = np.mod(hkllist[:,0]+100,2) != 0
                mask5 = np.mod(hkllist[:,1]+100,2) != 0
                mask6 = np.mod(hkllist[:,2]+100,2) != 0
                if(plane  == 'a'):
                    mask1 = np.logical_or(np.logical_and(mask1,mask5),np.logical_and(mask1,mask6))
                    mask2 = np.logical_or(np.logical_and(mask2,mask4),np.logical_and(mask2,mask6))
                    mask3 = np.logical_and(mask3,mask4)
                    
                    mask = np.logical_not(np.logical_or(mask1,np.logical_or(mask2,mask3)))
                elif(plane == 'b'):
                    mask1 = np.logical_and(mask1,mask5)
                    mask3 = np.logical_and(mask3,mask5)
                    mask = np.logical_not(np.logical_or(mask1,mask3))
                elif(plane == 'c'):
                    mask1 = np.logical_and(mask1,mask6)
                    mask2 = np.logical_and(mask2,mask6)
                    mask = np.logical_not(np.logical_or(mask1,mask2))
                elif(plane == 'n'):
                    mask4 = np.mod(hkllist[:,1]+hkllist[:,2]+100,2) != 0
                    mask5 = np.mod(hkllist[:,0]+hkllist[:,2]+100,2) != 0
                    mask6 = np.mod(hkllist[:,0]+hkllist[:,1]+100,2) != 0
                    mask1 = np.logical_not(np.logical_and(mask1,mask4))
                    mask2 = np.logical_not(np.logical_and(mask2,mask5))
                    mask3 = np.logical_not(np.logical_and(mask3,mask6))
                    mask = ~np.logical_or(~mask1,np.logical_or(~mask2,~mask3))
                elif(plane == 'd'):
                    mask4 = np.mod(hkllist[:,1]+hkllist[:,2]+100,4) != 0
                    mask5 = np.mod(hkllist[:,0]+hkllist[:,2]+100,4) != 0
                    mask6 = np.mod(hkllist[:,0]+hkllist[:,1]+100,4) != 0
                    mask1 = np.logical_not(np.logical_and(mask1,mask4))
                    mask2 = np.logical_not(np.logical_and(mask2,mask5))
                    mask3 = np.logical_not(np.logical_and(mask3,mask6))
                    mask = ~np.logical_or(~mask1,np.logical_or(~mask2,~mask3))
                else:
                    raise RuntimeError('omitglideplaneabsences: unknown glide plane encountered.')
                hkllist = hkllist[mask,:]
            if(ip == 2):
                mask1 = np.abs(hkllist[:,0]) == np.abs(hkllist[:,1])
                mask2 = np.abs(hkllist[:,1]) == np.abs(hkllist[:,2])
                mask3 = np.abs(hkllist[:,0]) == np.abs(hkllist[:,2])
                if(plane in ['a','b','c','n']):
                    mask4 = np.mod(hkllist[:,2]+100,2) != 0
                    mask5 = np.mod(hkllist[:,0]+100,2) != 0
                    mask6 = np.mod(hkllist[:,1]+100,2) != 0
                elif(plane == 'd'):
                    mask4 = np.mod(2*hkllist[:,0]+hkllist[:,2]+100,4) != 0
                    mask5 = np.mod(hkllist[:,0]+2*hkllist[:,1]+100,4) != 0
                    mask6 = np.mod(2*hkllist[:,0]+hkllist[:,1]+100,4) != 0
                else:
                    raise RuntimeError('omitglideplaneabsences: unknown glide plane encountered.')
                mask1 = np.logical_not(np.logical_and(mask1,mask4))
                mask2 = np.logical_not(np.logical_and(mask2,mask5))
                mask3 = np.logical_not(np.logical_and(mask3,mask6))
                mask = ~np.logical_or(~mask1,np.logical_or(~mask2,~mask3))
                hkllist = hkllist[mask,:]
        return hkllist

    def NonSymmorphicAbsences(self, hkllist):
        '''
        this function prunes hkl list for the screw axis and glide 
        plane absences
        '''
        planes = constants.SYS_AB[self.sgnum][0]
        for ip,p in enumerate(planes):
            if(p is not ''):
                hkllist = self.omitglideplaneabsences(hkllist, p, ip)
        axes = constants.SYS_AB[self.sgnum][1]
        for iax,ax in enumerate(axes):
            if(ax is not ''):
                hkllist = self.omitscrewaxisabsences(hkllist, ax, iax)
        return hkllist

    def ChooseSymmetric(self, hkllist, InversionSymmetry=True):
        '''
        this function takes a list of hkl vectors and 
        picks out a subset of the list picking only one
        of the symmetrically equivalent one. The convention
        is to choose the hkl with the most positive components.
        '''
        mask = np.ones(hkllist.shape[0],dtype=np.bool)
        laue = InversionSymmetry
        for i,g in enumerate(hkllist):
            if(mask[i]):
                geqv = self.CalcStar(g,'r',applyLaue=laue)
                for r in geqv[1:,]:
                    rid = np.where(np.all(r==hkllist,axis=1))
                    mask[rid] = False
        hkl = hkllist[mask,:].astype(np.int32)
        hkl_max = []
        for g in hkl:
            geqv = self.CalcStar(g,'r',applyLaue=laue)
            loc = np.argmax(np.sum(geqv,axis=1))
            gmax = geqv[loc,:]
            hkl_max.append(gmax)
        return np.array(hkl_max).astype(np.int32)

    def SortHKL(self, hkllist):
        '''
        this function sorts the hkllist by increasing |g| 
        i.e. decreasing d-spacing. If two vectors are same 
        length, then they are ordered with increasing 
        priority to l, k and h
        '''
        glen = []
        for g in hkllist:
            glen.append(np.round(self.CalcLength(g,'r'),8))
        # glen = np.atleast_2d(np.array(glen,dtype=np.float)).T
        dtype = [('glen', float), ('max', int), ('sum', int), ('h', int), ('k', int), ('l', int)]
        a = []
        for i,gl in enumerate(glen):
            g = hkllist[i,:]
            a.append((gl, np.max(g), np.sum(g), g[0], g[1], g[2]))
        a = np.array(a, dtype=dtype)
        isort = np.argsort(a, order=['glen','max','sum','l','k','h'])
        return hkllist[isort,:]

    def getHKLs(self, dmin):
        '''
        this function generates the symetrically unique set of 
        hkls up to a given dmin.
        dmin is in nm
        '''
        '''
        always have the centrosymmetric condition because of
        Friedels law for xrays so only 4 of the 8 octants
        are sampled for unique hkls. By convention we will
        ignore all l < 0
        '''
        hmin = -self.ih-1
        hmax = self.ih
        kmin = -self.ik-1
        kmax = self.ik
        lmin = -1
        lmax = self.il
        hkllist = np.array([[ih, ik, il] for ih in np.arange(hmax,hmin,-1) \
                  for ik in np.arange(kmax,kmin,-1) \
                  for il in np.arange(lmax,lmin,-1)])
        hkl_allowed = self.Allowed_HKLs(hkllist)
        hkl = []
        dsp = []
        hkl_dsp = []
        for g in hkl_allowed:
            # ignore [0 0 0] as it is the direct beam
            if(np.sum(np.abs(g)) != 0):
                dspace = 1./self.CalcLength(g,'r')
                if(dspace >= dmin):
                    hkl_dsp.append(g)
        '''
        we now have a list of g vectors which are all within dmin range
        plus the systematic absences due to lattice centering and glide
        planes/screw axis has been taken care of
        the next order of business is to go through the list and only pick
        out one of the symetrically equivalent hkls from the list.
        '''
        hkl_dsp = np.array(hkl_dsp).astype(np.int32)
        '''
        the inversionsymmetry switch enforces the application of the inversion
        symmetry regradless of whether the crystal has the symmetry or not
        this is necessary in the case of xrays due to friedel's law
        '''
        hkl = self.ChooseSymmetric(hkl_dsp, InversionSymmetry=True)
        '''
        finally sort in order of decreasing dspacing
        '''
        self.hkl = self.SortHKL(hkl)
        return self.hkl

    def Required_lp(self, p):
        return _rqpDict[self.latticeType][1](p)

class Phases_LeBail:
    ''' ======================================================================================================== 
        ======================================================================================================== 

    >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    >> @DATE:       05/20/2020 SS 1.0 original
    >> @DETAILS:    class to handle different phases in the LeBail fit. this is a stripped down
                    version of main Phase class for efficiency. only the components necessary for 
                    calculating peak positions are retained. further this will have a slight
                    modification to account for different wavelengths in the same phase name
        ======================================================================================================== 
        ======================================================================================================== 
    '''
    def _kev(x):
        return valWUnit('beamenergy','energy', x,'keV')

    def _nm(x):
        return valWUnit('lp', 'length', x, 'nm')

    def __init__(self, material_file=None, 
                 material_keys=None,
                 dmin = _nm(0.05),
                 wavelength={'alpha1':_nm(0.15406),'alpha2':_nm(0.154443)}
                 ):

        self.phase_dict = {}
        self.num_phases = 0
        self.wavelength = wavelength
        self.dmin = dmin

        if(material_file is not None):
            if(material_keys is not None):
                if(type(material_keys) is not list):
                    self.add(material_file, material_keys)
                else:
                    self.add_many(material_file, material_keys)

    def __str__(self):
        resstr = 'Phases in calculation:\n'
        for i,k in enumerate(self.phase_dict.keys()):
            resstr += '\t'+str(i+1)+'. '+k+'\n'
        return resstr

    def __getitem__(self, key):
        if(key in self.phase_dict.keys()):
            return self.phase_dict[key]
        else:
            raise ValueError('phase with name not found')

    def __setitem__(self, key, mat_cls):

        if(key in self.phase_dict.keys()):
            warnings.warn('phase already in parameter list. overwriting ...')
        if(isinstance(mat_cls, Material_LeBail)):
            self.phase_dict[key] = mat_cls
        else:
            raise ValueError('input not a material class')

    def __iter__(self):
        self.n = 0
        return self

    def __next__(self):
        if(self.n < len(self.phase_dict.keys())):
            res = list(self.phase_dict.keys())[self.n]
            self.n += 1
            return res
        else:
            raise StopIteration

    def __len__(self):
         return len(self.phase_dict)

    def add(self, material_file, material_key):

        self[material_key] = Material_LeBail(material_file, material_key, dmin=self.dmin)

    def add_many(self, material_file, material_keys):
        
        for k in material_keys:

            self[k] = Material_LeBail(material_file, k, dmin=self.dmin)

            self.num_phases += 1

        for k in self:
            self[k].pf = 1.0/len(self)

        self.material_file = material_file
        self.material_keys = material_keys

    def load(self, fname):
        '''
            >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
            >> @DATE:       06/08/2020 SS 1.0 original
            >> @DETAILS:    load parameters from yaml file
        '''
        with open(fname) as file:
            dic = yaml.load(file, Loader=yaml.FullLoader)

        for mfile in dic.keys():
            mat_keys = list(dic[mfile])
            self.add_many(mfile, mat_keys)

    def dump(self, fname):
        '''
            >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
            >> @DATE:       06/08/2020 SS 1.0 original
            >> @DETAILS:    dump parameters to yaml file
        '''
        dic = {}
        k = self.material_file
        dic[k] =  [m for m in self]

        with open(fname, 'w') as f:
            data = yaml.dump(dic, f, sort_keys=False)

class LeBail:
    ''' ======================================================================================================== 
        ======================================================================================================== 

    >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    >> @DATE:       05/19/2020 SS 1.0 original
    >> @DETAILS:    this is the main LeBail class and contains all the refinable parameters
                    for the analysis. Since the LeBail method has no structural information 
                    during refinement, the refinable parameters for this model will be:

                    1. a, b, c, alpha, beta, gamma : unit cell parameters
                    2. U, V, W : cagliotti paramaters
                    3. 2theta_0 : Instrumental zero shift error
                    4. eta1, eta2, eta3 : weight factor for gaussian vs lorentzian

                    @NOTE: All angles are always going to be in degrees
        ======================================================================================================== 
        ======================================================================================================== 
    '''

    def __init__(self,expt_file=None,param_file=None,phase_file=None,wavelength=None):

        self.initialize_expt_spectrum(expt_file)

        if(wavelength is not None):
            self.wavelength = wavelength

        self._tstart = time.time()
        self.initialize_phases(phase_file)
        self.initialize_parameters(param_file)
        self.initialize_Icalc()
        self.computespectrum()

        self._tstop = time.time()
        self.tinit = self._tstop - self._tstart
        self.niter = 0
        self.Rwplist  = np.empty([0])
        self.gofFlist = np.empty([0])

    def __str__(self):
        resstr = '<LeBail Fit class>\nParameters of the model are as follows:\n'
        resstr += self.params.__str__()
        return resstr

    def checkangle(ang, name):

        if(np.abs(ang) > 180.):
            warnings.warn(name + " : the absolute value of angles \
                                seems to be large > 180 degrees")

    def initialize_parameters(self, param_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    initialize parameter list from file. if no file given, then initialize
                        to some default values (lattice constants are for CeO2)

        '''
        params = Parameters()
        if(param_file is not None):
            if(path.exists(param_file)):
                params.load(param_file)
                '''
                this part initializes the lattice parameters in the 
                paramter list
                '''
                for p in self.phases:

                    mat = self.phases[p]
                    lp       = np.array(mat.lparms)
                    rid      = list(_rqpDict[mat.latticeType][0])

                    lp       = lp[rid]
                    name     = _lpname[rid]

                    for n,l in zip(name,lp):
                        nn = p+'_'+n
                        '''
                        is l is small, it is one of the length units
                        else it is an angle
                        '''
                        if(l < 10.):
                            params.add(nn,value=l,lb=l-0.05,ub=l+0.05,vary=False)
                        else:
                            params.add(nn,value=l,lb=l-1.,ub=l+1.,vary=False)

            else:
                raise FileError('parameter file doesn\'t exist.')
        else:
            '''
                first 6 are the lattice paramaters
                next three are cagliotti parameters
                next are the three gauss+lorentz mixing paramters
                final is the zero instrumental peak position error
            '''
            names   = ('a','b','c','alpha','beta','gamma',\
                      'U','V','W','eta1','eta2','eta3','tth_zero')
            values  = (5.415, 5.415, 5.415, 90., 90., 90., \
                        0.5, 0.5, 0.5, 1e-3, 1e-3, 1e-3, 0.)

            lbs         = (-np.Inf,) * len(names)
            ubs         = (np.Inf,)  * len(names)
            varies  = (False,)   * len(names)

            params.add_many(names,values=values,varies=varies,lbs=lbs,ubs=ubs)

        self.params = params

        self._U = self.params['U'].value
        self._V = self.params['V'].value
        self._W = self.params['W'].value
        self._P = self.params['P'].value
        self._X = self.params['X'].value
        self._Y = self.params['Y'].value
        self._eta1 = self.params['eta1'].value
        self._eta2 = self.params['eta2'].value
        self._eta3 = self.params['eta3'].value
        self._zero_error = self.params['zero_error'].value

    def params_vary_off(self):
        '''
            no params are varied
        '''
        for p in self.params:
            self.params[p].vary = False

    def params_vary_on(self):
        '''
            all params are varied
        '''
        for p in self.params:
            self.params[p].vary = True


    def initialize_expt_spectrum(self, expt_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    load the experimental spectum of 2theta-intensity
        '''
        # self.spectrum_expt = Spectrum.from_file()
        if(expt_file is not None):
            if(path.exists(expt_file)):
                self.spectrum_expt = Spectrum.from_file(expt_file,skip_rows=0)
                self.tth_max = np.amax(self.spectrum_expt._x)
                self.tth_min = np.amin(self.spectrum_expt._x)

                ''' also initialize statistical weights for the error calculation'''
                self.weights = 1.0 / np.sqrt(self.spectrum_expt.y)
                self.initialize_bkg()
            else:
                raise FileError('input spectrum file doesn\'t exist.')

    def initialize_bkg(self):

        '''
            the cubic spline seems to be the ideal route in terms
            of determining the background intensity. this involves 
            selecting a small (~5) number of points from the spectrum,
            usually called the anchor points. a cubic spline interpolation
            is performed on this subset to estimate the overall background.
            scipy provides some useful routines for this
        '''
        self.selectpoints()
        x = self.points[:,0]
        y = self.points[:,1]
        self.splinefit(x, y)

    def selectpoints(self):

        fig = plt.figure()
        ax = fig.add_subplot(111)
        ax.set_title('Select 5 points for background estimation')

        line = ax.plot(self.tth_list, self.spectrum_expt._y, '-b', picker=8)  # 5 points tolerance
        plt.show()

        self.points = np.asarray(plt.ginput(8,timeout=-1, show_clicks=True))
        plt.close()

    # cubic spline fit of background using custom points chosen from plot
    def splinefit(self, x, y):
        cs = CubicSpline(x,y)
        bkg = cs(self.tth_list)
        self.background = Spectrum(x=self.tth_list, y=bkg)


    def initialize_phases(self, phase_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    load the phases for the LeBail fits
        '''
        if(hasattr(self,'wavelength')):
            if(self.wavelength is not None):
                p = Phases_LeBail(wavelength=self.wavelength)
        else:
            p = Phases_LeBail()

        if(phase_file is not None):
            if(path.exists(phase_file)):
                p.load(phase_file)
            else:
                raise FileError('phase file doesn\'t exist.')
        self.phases = p

        self.calctth()

    def calctth(self):
        self.tth = {}
        for p in self.phases:
            self.tth[p] = {}
            for k,l in self.phases.wavelength.items():
                t = self.phases[p].getTTh(l.value)
                limit = np.logical_and(t >= self.tth_min,\
                                       t <= self.tth_max)
                self.tth[p][k] = t[limit]

    def initialize_Icalc(self):

        self.Icalc = {}
        for p in self.phases:
            self.Icalc[p] = {}
            for k,l in self.phases.wavelength.items():

                self.Icalc[p][k] = 1000.0 * np.ones(self.tth[p][k].shape)

    def CagliottiH(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    calculates the cagiotti parameter for the peak width
        '''
        th          = np.radians(0.5*tth)
        tanth       = np.tan(th)
        Hsq         = self.U * tanth**2 + self.V * tanth + self.W
        if(Hsq < 0.):
            Hsq = 1.0e-12
        self.Hcag   = np.sqrt(Hsq)

    def LorentzH(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       07/20/2020 SS 1.0 original
        >> @DETAILS:    calculates the size and strain broadening for Lorentzian peak
        '''
        th = np.radians(0.5*tth)
        tanth       = np.tan(th)
        cth         = np.cos(th)
        self.gamma = self.X/cth + self.Y * tanth

    def MixingFact(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    calculates the mixing factor eta
        '''
        self.eta = self.eta1 + self.eta2 * tth + self.eta3 * (tth)**2

        if(self.eta > 1.0):
            self.eta = 1.0

        elif(self.eta < 0.0):
            self.eta = 0.0

    def Gaussian(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the gaussian peak profile
        '''

        H  = self.Hcag
        cg = 4.*np.log(2.)
        self.GaussianI = (np.sqrt(cg/np.pi)/H) * np.exp( -cg * ((self.tth_list - tth)/H)**2 )

    def Lorentzian(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the lorentzian peak profile
        '''

        H = self.gamma
        cl = 4.
        self.LorentzI = (2./np.pi/H) / ( 1. + cl*((self.tth_list - tth)/H)**2)

    def PseudoVoight(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the pseudo-voight function as weighted 
                        average of gaussian and lorentzian
        '''

        self.CagliottiH(tth)
        self.Gaussian(tth)
        self.LorentzH(tth)
        self.Lorentzian(tth)
        self.MixingFact(tth)
        self.PV = self.eta * self.GaussianI + \
                  (1.0 - self.eta) * self.LorentzI

    def IntegratedIntensity(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    Integrated intensity of the pseudo-voight peak
        '''
        return np.trapz(self.PV, self.tth_list)

    def computespectrum(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    compute the simulated spectrum
        '''
        x = self.tth_list
        y = np.zeros(x.shape)

        for iph,p in enumerate(self.phases):

            for k,l in self.phases.wavelength.items():
        
                Ic = self.Icalc[p][k]

                tth = self.tth[p][k] + self.zero_error
                n = np.min((tth.shape[0],Ic.shape[0]))

                for i in range(n):

                    t = tth[i]
                    self.PseudoVoight(t)

                    y += Ic[i] * self.PV

        self.spectrum_sim = Spectrum(x=x, y=y)
        self.spectrum_sim = self.spectrum_sim + self.background

    def CalcIobs(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    this is one of the main functions to partition the expt intensities
                        to overlapping peaks in the calculated pattern
        '''

        self.Iobs = {}
        for iph,p in enumerate(self.phases):

            self.Iobs[p] = {}

            for k,l in self.phases.wavelength.items():
                Ic = self.Icalc[p][k]

                tth = self.tth[p][k] + self.zero_error

                Iobs = []
                n = np.min((tth.shape[0],Ic.shape[0]))

                for i in range(n):
                    t = tth[i]
                    self.PseudoVoight(t)

                    y   = self.PV * Ic[i]
                    _,yo  = self.spectrum_expt.data
                    _,yc  = self.spectrum_sim.data

                    I = np.trapz(yo * y / yc, self.tth_list)
                    Iobs.append(I)

                self.Iobs[p][k] = np.array(Iobs)

    def calcRwp(self, params):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the weighted error between calculated and
                        experimental spectra. goodness of fit is also calculated. the 
                        weights are the inverse squareroot of the experimental intensities
        '''

        '''
        the err variable is the difference between simulated and experimental spectra
        '''
        for p in params:
            if(hasattr(self, p)):
                setattr(self, p, params[p].value)

        for p in self.phases:

            mat = self.phases[p]

            '''
            PART 1: update the lattice parameters
            '''
            lp = []

            pre = p + '_'
            if(pre+'a' in params):
                if(params[pre+'a'].vary):
                    lp.append(params[pre+'a'].value)
            if(pre+'b' in params):
                if(params[pre+'b'].vary):
                    lp.append(params[pre+'b'].value)
            if(pre+'c' in params):
                if(params[pre+'c'].vary):
                    lp.append(params[pre+'c'].value)
            if(pre+'alpha' in params):
                if(params[pre+'alpha'].vary):
                    lp.append(params[pre+'alpha'].value)
            if(pre+'beta' in params):
                if(params[pre+'beta'].vary):
                    lp.append(params[pre+'beta'].value)
            if(pre+'gamma' in params):
                if(params[pre+'gamma'].vary):
                    lp.append(params[pre+'gamma'].value)

            if(not lp):
                pass
            else:
                lp = self.phases[p].Required_lp(lp)
                self.phases[p].lparms = np.array(lp)
                self.phases[p]._calcrmt()

        self.calctth()
        self.computespectrum()

        self.err = (self.spectrum_sim - self.spectrum_expt)

        errvec = np.sqrt(self.weights * self.err._y**2)

        ''' weighted sum of square '''
        wss = np.trapz(self.weights * self.err._y**2, self.err._x)

        den = np.trapz(self.weights * self.spectrum_sim._y**2, self.spectrum_sim._x)

        ''' standard Rwp i.e. weighted residual '''
        Rwp = np.sqrt(wss/den)

        ''' number of observations to fit i.e. number of data points '''
        N = self.spectrum_sim._y.shape[0]

        ''' number of independent parameters in fitting '''
        P = len(params)
        Rexp = np.sqrt((N-P)/den)

        # Rwp and goodness of fit parameters
        self.Rwp = Rwp
        self.gofF = (Rwp / Rexp)**2

        return errvec

    def initialize_lmfit_parameters(self):

        params = lmfit.Parameters()

        for p in self.params:
            par = self.params[p]
            if(par.vary):
                params.add(p, value=par.value, min=par.lb, max = par.ub)

        return params

    def update_parameters(self):

        for p in self.res.params:
            par = self.res.params[p]
            self.params[p].value = par.value

    def RefineCycle(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    this is one refinement cycle for the least squares, typically few
                        10s to 100s of cycles may be required for convergence
        '''
        self.CalcIobs()
        self.Icalc = self.Iobs

        self.res = self.Refine()
        self.update_parameters()
        self.niter += 1
        self.Rwplist  = np.append(self.Rwplist, self.Rwp)
        self.gofFlist = np.append(self.gofFlist, self.gofF)
        print('Finished iteration. Rwp: {:.3f} % goodness of fit: {:.3f}'.format(self.Rwp*100., self.gofF))

    def Refine(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    this routine performs the least squares refinement for all variables
                        which are allowed to be varied.
        '''

        params = self.initialize_lmfit_parameters()

        fdict = {'ftol':1e-4, 'xtol':1e-4, 'gtol':1e-4, \
                 'verbose':0, 'max_nfev':8}

        fitter = lmfit.Minimizer(self.calcRwp, params)

        res = fitter.least_squares(**fdict)
        return res

    @property
    def U(self):
        return self._U

    @U.setter
    def U(self, Uinp):
        self._U = Uinp
        # self.computespectrum()
        return

    @property
    def V(self):
        return self._V

    @V.setter
    def V(self, Vinp):
        self._V = Vinp
        # self.computespectrum()
        return

    @property
    def W(self):
        return self._W

    @W.setter
    def W(self, Winp):
        self._W = Winp
        # self.computespectrum()
        return

    @property
    def P(self):
        return self._P

    @P.setter
    def P(self, Pinp):
        self._P = Pinp
        return

    @property
    def X(self):
        return self._X

    @X.setter
    def X(self, Xinp):
        self._X = Xinp
        return

    @property
    def Y(self):
        return self._Y

    @Y.setter
    def Y(self, Yinp):
        self._Y = Yinp
        return

    @property
    def gamma(self):
        return self._gamma
    
    @gamma.setter
    def gamma(self, val):
        self._gamma = val

    @property
    def Hcag(self):
        return self._Hcag

    @Hcag.setter
    def Hcag(self, val):
        self._Hcag = val

    @property
    def eta1(self):
        return self._eta1

    @eta1.setter
    def eta1(self, val):
        self._eta1 = val
        # self.computespectrum()
        return

    @property
    def eta2(self):
        return self._eta2

    @eta2.setter
    def eta2(self, val):
        self._eta2 = val
        # self.computespectrum()
        return

    @property
    def eta3(self):
        return self._eta3

    @eta3.setter
    def eta3(self, val):
        self._eta3 = val
        # self.computespectrum()
        return

    @property
    def tth_list(self):
        return self.spectrum_expt._x

    @property
    def zero_error(self):
        return self._zero_error
    
    @zero_error.setter
    def zero_error(self, value):
        self._zero_error = value
        # self.computespectrum()
        return

class LeBail_FPA:
    ''' ======================================================================================================== 
        ======================================================================================================== 

    >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    >> @DATE:       07/31/2020 SS 1.0 original
    >> @DETAILS:    this is the Lebail class using the fundamental parameter approach
                    the peak shapes are computed as convolution of different contributions

                    @NOTE: All angles are always going to be in degrees
        ======================================================================================================== 
        ======================================================================================================== 
    '''
    def __init__(self,expt_file=None,param_file=None,phase_file=None,flux_file=None):

        self.zero_error = 0.
        self.initialize_expt_spectrum(expt_file)

        self.extract_wavelength(flux_file)
        self._tstart = time.time()
        self.initialize_phases(phase_file)
        self.initialize_parameters(param_file)
        self.initialize_FP_profiles()
        self.initialize_Icalc()
        self.computespectrum()

        self._tstop = time.time()
        self.tinit = self._tstop - self._tstart
        self.niter = 0
        self.Rwplist  = np.empty([0])
        self.gofFlist = np.empty([0])

    def extract_wavelength(self, flux_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    load the spectum of the xray beam. this is written especially with 
                        the pink beam in mind
        '''
        if(flux_file is not None):
            fid = open(flux_file, 'r')
            mat = []
            for line in fid:
                mat.append([float(x) for x in line.split()])
            mat = np.array(mat)

            self.mat_wavelengths = 1e-10 * 12.39841984/mat[:,0]
            self.mat_intensities = mat[:,1]/np.trapz(mat[:,1])
            self.dominant_wavelength = 0.52368e-10 #self.mat_wavelengths[np.argmax(self.mat_intensities)]

        else:
            raise FileError('Need to supply the flux-energy file')

    def initialize_parameters(self, param_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    initialize parameter list from file. if no file given, then initialize
                        to some default values (lattice constants are for CeO2)

        '''
        params = Parameters()
        if(param_file is not None):
            if(path.exists(param_file)):
                params.load(param_file)
                '''
                this part initializes the lattice parameters in the 
                paramter list
                '''
                for p in self.phases:

                    mat = self.phases[p]
                    lp       = np.array(mat.lparms)
                    rid      = list(_rqpDict[mat.latticeType][0])

                    lp       = lp[rid]
                    name     = _lpname[rid]

                    for n,l in zip(name,lp):
                        nn = p+'_'+n
                        '''
                        is l is small, it is one of the length units
                        else it is an angle
                        '''
                        if(l < 10.):
                            params.add(nn,value=l,lb=l-0.05,ub=l+0.05,vary=False)
                        else:
                            params.add(nn,value=l,lb=l-1.,ub=l+1.,vary=False)

            else:
                raise FileError('parameter file doesn\'t exist.')

        else:
            raise FileError('parameter file not specified.')

        self.params = params

        self._gauss_width = self.params['gauss_width'].value
        self._lor_width = self.params['gauss_width'].value
        self._crystallite_size = self.params['crystallite_size'].value
        self._zero_error = self.params['zero_error'].value

    def initialize_expt_spectrum(self, expt_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    load the experimental spectum of 2theta-intensity
        '''
        # self.spectrum_expt = Spectrum.from_file()
        if(expt_file is not None):
            if(path.exists(expt_file)):
                self.spectrum_expt = Spectrum.from_file(expt_file,skip_rows=0)
                self.tth_max = np.amax(self.spectrum_expt._x)
                self.tth_min = np.amin(self.spectrum_expt._x)
                ''' also initialize statistical weights for the error calculation'''
                self.weights = 1.0 / np.sqrt(self.spectrum_expt.y)
                self.initialize_bkg()
            else:
                raise FileError('input spectrum file doesn\'t exist.')

    def initialize_bkg(self):
        '''
            the cubic spline seems to be the ideal route in terms
            of determining the background intensity. this involves 
            selecting a small (~5) number of points from the spectrum,
            usually called the anchor points. a cubic spline interpolation
            is performed on this subset to estimate the overall background.
            scipy provides some useful routines for this
        '''
        self.selectpoints()
        x = self.points[:,0]
        y = self.points[:,1]
        self.splinefit(x, y)

    def selectpoints(self):
        fig = plt.figure()
        ax = fig.add_subplot(111)
        ax.set_title('Select 5 points for background estimation')
        line = ax.plot(self.tth_list, self.spectrum_expt._y, '-b', picker=8)  # 5 points tolerance
        plt.show()
        self.points = np.asarray(plt.ginput(8,timeout=-1, show_clicks=True))
        plt.close()


    # cubic spline fit of background using custom points chosen from plot
    def splinefit(self, x, y):
        cs = CubicSpline(x,y)
        bkg = cs(self.tth_list)
        self.background = Spectrum(x=self.tth_list, y=bkg)

    def initialize_phases(self, phase_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    load the phases for the LeBail fits
        '''
        if(hasattr(self,'wavelength')):
            if(self.wavelength is not None):
                p = Phases_LeBail(wavelength=self.wavelength)
        else:
            p = Phases_LeBail()
        if(phase_file is not None):
            if(path.exists(phase_file)):
                p.load(phase_file)
            else:
                raise FileError('phase file doesn\'t exist.')
        self.phases = p
        self.calctth()


    def calctth(self):
        self.tth = {}
        for p in self.phases:
            self.tth[p] = {}
            t = self.phases[p].getTTh(self.dominant_wavelength*1e9)
            limit = np.logical_and(t >= self.tth_min,\
                                   t <= self.tth_max)
            self.tth[p] = t[limit]


    def initialize_Icalc(self):
        self.Icalc = {}
        for p in self.phases:
            self.Icalc[p] = 1000.0 * np.ones(self.tth[p].shape)

    def initialize_FP_profiles(self):

        self.window_width = 25.0

        self.FP = FPA.FP_profile(anglemode="twotheta",
        output_gaussian_smoother_bins_sigma=1.0,
        oversampling=2)

        self.FP.debug_cache=False

        '''
        set parameters for each convolver
        this part makes the convolver for the emission spectrum
        of the x-rays

        @params:
        mat_wavelengths is the vector of wavelengths in the spectrum
        mat_intensities is the vector of weights for each wavelength
        mat_gauss_widths is the vector of gaussian widths for each of the wavelengths
        mat_lor_widths is the vector of lorentzian widths for each of the wavelengths
        crystallite_size_gauss is the average crystallite size for gaussian broadening in inverse m
        crystallite_size_gauss is the average crystallite size for lorentzian broadening in inverse m
        '''
        mat_gauss_widths = np.array([self.gauss_width]*self.mat_wavelengths.shape[0]) 
        mat_lor_widths   = np.array([self.lor_width]*self.mat_wavelengths.shape[0])

        gauss_crystallite_size = self.crystallite_size
        lor_crystallite_size = self.crystallite_size

        self.FP.set_parameters(convolver="emission",
            emiss_wavelengths = self.mat_wavelengths,
            emiss_intensities = self.mat_intensities,
            emiss_gauss_widths = mat_gauss_widths,
            emiss_lor_widths = mat_lor_widths,
            crystallite_size_gauss = gauss_crystallite_size,
            crystallite_size_lor = lor_crystallite_size)

        '''
        set up parameters for the absorption convolver

        @params:
        absorption coefficient is the exponential coefficient in inverse m
        sample_thickness is the thickness of the sample in transmission
        '''
        self.FP.set_parameters(convolver="absorption",
        absorption_coefficient=800.0*100, #like LaB6, in m^(-1)
        sample_thickness=1e-3)

        # self.FP.set_parameters(convolver="size_distribution",
        # lognormal_mean=4.35,
        # lognormal_std=0.387,
        # )

        '''
        set up parameters for the silicon position sensitive detector

        @params:
        si_psd_window_bounds 
        '''
        self.FP.set_parameters(convolver="si_psd",
        si_psd_window_bounds=(0.,2.5e-3))

    def computespectrum(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    compute the simulated spectrum
        '''
        x = self.tth_list
        y = np.zeros(x.shape)
        ww = self.window_width

        for iph,p in enumerate(self.phases):

            Ic = self.Icalc[p]

            tth = self.tth[p] + self.zero_error
            n = np.min((tth.shape[0],Ic.shape[0]))

            for i in range(n):

                twotheta_x = tth[i]

                #put the compute window in the right place and clear all histories
                self.FP.set_window(twotheta_output_points=1000,
                    twotheta_window_center_deg=twotheta_x,
                    twotheta_window_fullwidth_deg=ww,
                )

                #set parameters which are shared by many things
                self.FP.set_parameters(twotheta0_deg=twotheta_x,
                    dominant_wavelength=self.dominant_wavelength,
                    diffractometer_radius=89.0e-3)

                self.FP.set_parameters(equatorial_divergence_deg=1.0)
  
                prof = self.FP.compute_line_profile()
                xx = prof.twotheta_deg
                yy = prof.peak/np.trapz(prof.peak, xx)
                spline = CubicSpline(xx,yy,extrapolate=False) 
                y  += Ic[i] * np.nan_to_num(spline(x)) 

        self.spectrum_sim = Spectrum(x=x, y=y)
        self.spectrum_sim = self.spectrum_sim + self.background

    def CalcIobs(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    this is one of the main functions to partition the expt intensities
                        to overlapping peaks in the calculated pattern
        '''

        self.Iobs = {}
        ww = self.window_width
        for iph,p in enumerate(self.phases):

            Ic = self.Icalc[p]

            tth = self.tth[p] + self.zero_error

            Iobs = []
            n = np.min((tth.shape[0],Ic.shape[0]))

            for i in range(n):

                twotheta_x = tth[i]
                
                #put the compute window in the right place and clear all histories
                self.FP.set_window(twotheta_output_points=500,
                    twotheta_window_center_deg=twotheta_x,
                    twotheta_window_fullwidth_deg=ww,
                )

                #set parameters which are shared by many things
                self.FP.set_parameters(twotheta0_deg=twotheta_x,
                    dominant_wavelength=self.dominant_wavelength,
                    diffractometer_radius=217.5e-3)

                self.FP.set_parameters(equatorial_divergence_deg=-1.0)

                prof = self.FP.compute_line_profile()
                xx = prof.twotheta_deg
                yy = prof.peak/np.trapz(prof.peak, xx)

                spline = CubicSpline(xx,yy,extrapolate=False) 
                y  = Ic[i] * np.nan_to_num(spline(self.tth_list)) 

                _,yo  = self.spectrum_expt.data
                _,yc  = self.spectrum_sim.data

                I = np.trapz(yo * y / yc, self.tth_list)
                Iobs.append(I)

            self.Iobs[p] = np.array(Iobs)

    def calcRwp(self, params):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the weighted error between calculated and
                        experimental spectra. goodness of fit is also calculated. the 
                        weights are the inverse squareroot of the experimental intensities
        '''

        '''
        the err variable is the difference between simulated and experimental spectra
        '''

        if(self.params['zero_error'].vary):
            self.zero_error = self.params['zero_error'].value
        if( self.params['gauss_width'].vary or 
            self.params['lor_width'].vary or
            self.params['crystallite_size'].vary):

            mat_gauss_widths = np.array([self.params['gauss_width'].value]*self.mat_wavelengths.shape[0])
            mat_lor_widths = np.array([self.params['lor_width'].value]*self.mat_wavelengths.shape[0])

            self._crystallite_size   = self.params['crystallite_size'].value
            self._gauss_width        = self.params['gauss_width'].value
            self._lor_width          = self.params['lor_width'].value

            self.FP.set_parameters(convolver="emission",
                emiss_wavelengths = self.mat_wavelengths,
                emiss_intensities = self.mat_intensities,
                emiss_gauss_widths = mat_gauss_widths,
                emiss_lor_widths = mat_lor_widths,
                crystallite_size_gauss = self.crystallite_size*1e-9,
                crystallite_size_lor = self.crystallite_size*1e-9)

        for p in self.phases:

            mat = self.phases[p]

            '''
            PART 1: update the lattice parameters
            '''
            lp = []

            pre = p + '_'
            if(pre+'a' in params):
                if(params[pre+'a'].vary):
                    lp.append(params[pre+'a'].value)
            if(pre+'b' in params):
                if(params[pre+'b'].vary):
                    lp.append(params[pre+'b'].value)
            if(pre+'c' in params):
                if(params[pre+'c'].vary):
                    lp.append(params[pre+'c'].value)
            if(pre+'alpha' in params):
                if(params[pre+'alpha'].vary):
                    lp.append(params[pre+'alpha'].value)
            if(pre+'beta' in params):
                if(params[pre+'beta'].vary):
                    lp.append(params[pre+'beta'].value)
            if(pre+'gamma' in params):
                if(params[pre+'gamma'].vary):
                    lp.append(params[pre+'gamma'].value)

            if(not lp):
                pass
            else:
                lp = self.phases[p].Required_lp(lp)
                self.phases[p].lparms = np.array(lp)
                self.phases[p]._calcrmt()
                self.calctth()

        self.computespectrum()

        self.err = (self.spectrum_sim - self.spectrum_expt)

        errvec = np.sqrt(self.weights * self.err._y**2)

        ''' weighted sum of square '''
        wss = np.trapz(self.weights * self.err._y**2, self.err._x)

        den = np.trapz(self.weights * self.spectrum_sim._y**2, self.spectrum_sim._x)

        ''' standard Rwp i.e. weighted residual '''
        Rwp = np.sqrt(wss/den)

        ''' number of observations to fit i.e. number of data points '''
        N = self.spectrum_sim._y.shape[0]

        ''' number of independent parameters in fitting '''
        P = len(params)
        Rexp = np.sqrt((N-P)/den)

        # Rwp and goodness of fit parameters
        self.Rwp = Rwp
        self.gofF = (Rwp / Rexp)**2

        return errvec

    def initialize_lmfit_parameters(self):

        params = lmfit.Parameters()

        for p in self.params:
            par = self.params[p]
            if(par.vary):
                params.add(p, value=par.value, min=par.lb, max = par.ub)

        return params

    def update_parameters(self):

        for p in self.res.params:
            par = self.res.params[p]
            self.params[p].value = par.value

    def RefineCycle(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    this is one refinement cycle for the least squares, typically few
                        10s to 100s of cycles may be required for convergence
        '''
        self.CalcIobs()
        self.Icalc = self.Iobs
        self.res = self.Refine()
        self.update_parameters()
        self.niter += 1
        self.Rwplist  = np.append(self.Rwplist, self.Rwp)
        self.gofFlist = np.append(self.gofFlist, self.gofF)
        print('Finished iteration. Rwp: {:.3f} % goodness of fit: {:.3f}'.format(self.Rwp*100., self.gofF))

    def Refine(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    this routine performs the least squares refinement for all variables
                        which are allowed to be varied.
        '''

        params = self.initialize_lmfit_parameters()
        for p in params: 
            if(params[p].vary):
                print(p, params[p].value)
        print('\n')

        fdict = {'ftol':1e-4, 'xtol':1e-4, 'gtol':1e-4, \
                 'verbose':0, 'max_nfev':100}

        fitter = lmfit.Minimizer(self.calcRwp, params)

        res = fitter.least_squares(**fdict)
        return res

    @property
    def tth_list(self):
        return self.spectrum_expt._x

    @property
    def gauss_width(self):
        return self._gauss_width
    
    @property
    def lor_width(self):
        return self._lor_width

    @property
    def crystallite_size(self):
        return self._crystallite_size
    

    @property
    def zero_error(self):
        return self._zero_error
    
    @zero_error.setter
    def zero_error(self, value):
        self._zero_error = value
        # self.computespectrum()
        return

class LeBail_Asym:
    ''' ======================================================================================================== 
        ======================================================================================================== 

    >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    >> @DATE:       05/19/2020 SS 1.0 original
    >> @DETAILS:    this is the main LeBail class and contains all the refinable parameters
                    for the analysis. Since the LeBail method has no structural information 
                    during refinement, the refinable parameters for this model will be:

                    1. a, b, c, alpha, beta, gamma : unit cell parameters
                    2. U, V, W : cagliotti paramaters
                    3. 2theta_0 : Instrumental zero shift error
                    4. eta1, eta2, eta3 : weight factor for gaussian vs lorentzian

                    @NOTE: All angles are always going to be in degrees
        ======================================================================================================== 
        ======================================================================================================== 
    '''

    def __init__(self,expt_file=None,param_file=None,phase_file=None,wavelength=None):

        self.initialize_expt_spectrum(expt_file)

        '''
        wavelength for the FPA needs to be in Angstroms
        '''
        if(wavelength is not None):
            self.wavelength = wavelength

        self._tstart = time.time()
        self.initialize_phases(phase_file)
        self.initialize_parameters(param_file)
        self.initialize_Icalc()
        self.computespectrum()

        self._tstop = time.time()
        self.tinit = self._tstop - self._tstart
        self.niter = 0
        self.Rwplist  = np.empty([0])
        self.gofFlist = np.empty([0])

    def __str__(self):
        resstr = '<LeBail Fit class>\nParameters of the model are as follows:\n'
        resstr += self.params.__str__()
        return resstr

    def checkangle(ang, name):

        if(np.abs(ang) > 180.):
            warnings.warn(name + " : the absolute value of angles \
                                seems to be large > 180 degrees")

    def initialize_parameters(self, param_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    initialize parameter list from file. if no file given, then initialize
                        to some default values (lattice constants are for CeO2)

        '''
        params = Parameters()
        if(param_file is not None):
            if(path.exists(param_file)):
                params.load(param_file)
                '''
                this part initializes the lattice parameters in the 
                paramter list
                '''
                for p in self.phases:

                    mat = self.phases[p]
                    lp       = np.array(mat.lparms)
                    rid      = list(_rqpDict[mat.latticeType][0])

                    lp       = lp[rid]
                    name     = _lpname[rid]

                    for n,l in zip(name,lp):
                        nn = p+'_'+n
                        '''
                        is l is small, it is one of the length units
                        else it is an angle
                        '''
                        if(l < 10.):
                            params.add(nn,value=l,lb=l-0.05,ub=l+0.05,vary=False)
                        else:
                            params.add(nn,value=l,lb=l-1.,ub=l+1.,vary=False)

            else:
                raise FileError('parameter file doesn\'t exist.')
        else:
            '''
                first 6 are the lattice paramaters
                next three are cagliotti parameters
                next are the three gauss+lorentz mixing paramters
                final is the zero instrumental peak position error
            '''
            names   = ('a','b','c','alpha','beta','gamma',\
                      'U','V','W','eta1','eta2','eta3','tth_zero')
            values  = (5.415, 5.415, 5.415, 90., 90., 90., \
                        0.5, 0.5, 0.5, 1e-3, 1e-3, 1e-3, 0.)

            lbs         = (-np.Inf,) * len(names)
            ubs         = (np.Inf,)  * len(names)
            varies  = (False,)   * len(names)

            params.add_many(names,values=values,varies=varies,lbs=lbs,ubs=ubs)

        self.params = params

        self._Ul = self.params['Ul'].value
        self._Vl = self.params['Vl'].value
        self._Wl = self.params['Wl'].value
        self._Pl = self.params['Pl'].value
        self._Xl = self.params['Xl'].value
        self._Yl = self.params['Yl'].value
        self._Ur = self.params['Ur'].value
        self._Vr = self.params['Vr'].value
        self._Wr = self.params['Wr'].value
        self._Pr = self.params['Pr'].value
        self._Xr = self.params['Xr'].value
        self._Yr = self.params['Yr'].value
        self._eta1 = self.params['eta1'].value
        self._eta2 = self.params['eta2'].value
        self._eta3 = self.params['eta3'].value
        self._zero_error = self.params['zero_error'].value

    def params_vary_off(self):
        '''
            no params are varied
        '''
        for p in self.params:
            self.params[p].vary = False

    def params_vary_on(self):
        '''
            all params are varied
        '''
        for p in self.params:
            self.params[p].vary = True


    def initialize_expt_spectrum(self, expt_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    load the experimental spectum of 2theta-intensity
        '''
        # self.spectrum_expt = Spectrum.from_file()
        if(expt_file is not None):
            if(path.exists(expt_file)):
                self.spectrum_expt = Spectrum.from_file(expt_file,skip_rows=0)
                self.tth_max = np.amax(self.spectrum_expt._x)
                self.tth_min = np.amin(self.spectrum_expt._x)

                ''' also initialize statistical weights for the error calculation'''
                self.weights = 1.0 / np.sqrt(self.spectrum_expt.y)
                self.initialize_bkg()
            else:
                raise FileError('input spectrum file doesn\'t exist.')

    def initialize_bkg(self):

        '''
            the cubic spline seems to be the ideal route in terms
            of determining the background intensity. this involves 
            selecting a small (~5) number of points from the spectrum,
            usually called the anchor points. a cubic spline interpolation
            is performed on this subset to estimate the overall background.
            scipy provides some useful routines for this
        '''
        self.selectpoints()
        x = self.points[:,0]
        y = self.points[:,1]
        self.splinefit(x, y)

    def selectpoints(self):

        fig = plt.figure()
        ax = fig.add_subplot(111)
        ax.set_title('Select 7 points for background estimation')

        line = ax.plot(self.tth_list, self.spectrum_expt._y, '-b', picker=7)  # 5 points tolerance
        plt.show()

        self.points = np.asarray(plt.ginput(7,timeout=-1, show_clicks=True))
        plt.close()

    # cubic spline fit of background using custom points chosen from plot
    def splinefit(self, x, y):
        cs = CubicSpline(x,y)
        bkg = cs(self.tth_list)
        self.background = Spectrum(x=self.tth_list, y=bkg)


    def initialize_phases(self, phase_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    load the phases for the LeBail fits
        '''
        if(hasattr(self,'wavelength')):
            if(self.wavelength is not None):
                p = Phases_LeBail(wavelength=self.wavelength)
        else:
            p = Phases_LeBail()

        if(phase_file is not None):
            if(path.exists(phase_file)):
                p.load(phase_file)
            else:
                raise FileError('phase file doesn\'t exist.')
        self.phases = p

        self.calctth()

    def calctth(self):
        self.tth = {}
        for p in self.phases:
            self.tth[p] = {}
            for k,l in self.phases.wavelength.items():
                t = self.phases[p].getTTh(l.value)
                limit = np.logical_and(t >= self.tth_min,\
                                       t <= self.tth_max)
                self.tth[p][k] = t[limit]

    def initialize_Icalc(self):

        self.Icalc = {}
        for p in self.phases:
            self.Icalc[p] = {}
            for k,l in self.phases.wavelength.items():

                self.Icalc[p][k] = 1000.0 * np.ones(self.tth[p][k].shape)

    def CagliottiH(self, tth, branch):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
                        07/20/2020 SS 1.1 branch keyword for asymmetric profiles
        >> @DETAILS:    calculates the cagiotti parameter for the peak width

        '''
        th          = np.radians(0.5*tth)
        tanth       = np.tan(th)
        cth         = np.cos(th)
        if(branch == 'l'):
            Hsq         = self.Ul * tanth**2 + self.Vl * tanth + self.Wl + self.Pl / cth**2
        elif(branch == 'r'):
            Hsq         = self.Ur * tanth**2 + self.Vr * tanth + self.Wr + self.Pr / cth**2

        if(Hsq < 0.):
            Hsq = 1.0e-12
        self.Hcag   = np.sqrt(Hsq)

    def LorentzH(self, tth, branch):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       07/20/2020 SS 1.0 original
        >> @DETAILS:    calculates the size and strain broadening for Lorentzian peak
        '''
        th = np.radians(0.5*tth)
        tanth       = np.tan(th)
        cth         = np.cos(th)
        if(branch == 'l'):
            self.gamma = self.Xl/cth + self.Yl * tanth
        elif(branch == 'r'):
            self.gamma = self.Xr/cth + self.Yr * tanth

        if(self.gamma < 0.):
            self.gamma = 1e-6

    def MixingFact(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    calculates the mixing factor eta
        '''
        self.eta = self.eta1 + self.eta2 * tth + self.eta3 * (tth)**2

        if(self.eta > 1.0):
            self.eta = 1.0

        elif(self.eta < 0.0):
            self.eta = 0.0

    def Gaussian(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the gaussian peak profile
        '''
        mask = self.tth_list < tth
        cg = 4.*np.log(2.)

        self.CagliottiH(tth, 'l')
        H  = self.Hcag
        Il = (np.sqrt(cg/np.pi)/H) * np.exp( -cg * ((self.tth_list[mask] - tth)/H)**2 )

        self.CagliottiH(tth, 'r')
        H  = self.Hcag
        Ir = (np.sqrt(cg/np.pi)/H) * np.exp( -cg * ((self.tth_list[~mask] - tth)/H)**2 )

        if(Il.size == 0):
            a = 0.
            b = 1.
        elif(Ir.size == 0):
            a = 1.
            b = 0.
        else:
            Ilm = np.amax(Il)
            Irm = np.amax(Ir)
            if(Ilm == 0):
                a = 1.
                b = 0.
            elif(Irm == 0):
                a = 0.
                b = 1.
            else:
                b = 2./(1. + Irm/Ilm)
                a = b * Irm / Ilm

        self.GaussianI = np.hstack((a*Il, b*Ir))

    def Lorentzian(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the lorentzian peak profile
        '''
        mask = self.tth_list < tth
        cl = 4.

        self.LorentzH(tth, 'l')
        H = self.gamma
        Il = (2./np.pi/H) / ( 1. + cl*((self.tth_list[mask] - tth)/H)**2)

        self.LorentzH(tth, 'r')
        H = self.gamma
        Ir = (2./np.pi/H) / ( 1. + cl*((self.tth_list[~mask] - tth)/H)**2)

        if(Il.size == 0):
            a = 0.
            b = 1.
        elif(Ir.size == 0):
            a = 1.
            b = 0.
        else:
            Ilm = np.amax(Il)
            Irm = np.amax(Ir)
            if(Ilm == 0):
                a = 1.
                b = 0.
            elif(Irm == 0):
                a = 0.
                b = 1.
            else:
                b = 2./(1. + Irm/Ilm)
                a = b * Irm / Ilm

        self.LorentzI = np.hstack((a*Il, b*Ir))

    def PseudoVoight(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the pseudo-voight function as weighted 
                        average of gaussian and lorentzian
        '''

        self.Gaussian(tth)
        self.Lorentzian(tth)
        self.MixingFact(tth)

        self.PV = self.eta * self.GaussianI + \
                  (1.0 - self.eta) * self.LorentzI

    def IntegratedIntensity(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    Integrated intensity of the pseudo-voight peak
        '''
        return np.trapz(self.PV, self.tth_list)

    def computespectrum(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    compute the simulated spectrum
        '''
        x = self.tth_list
        y = np.zeros(x.shape)

        for iph,p in enumerate(self.phases):

            for k,l in self.phases.wavelength.items():
        
                Ic = self.Icalc[p][k]

                tth = self.tth[p][k] + self.zero_error
                n = np.min((tth.shape[0],Ic.shape[0]))

                for i in range(n):

                    t = tth[i]
                    self.PseudoVoight(t)

                    y += Ic[i] * self.PV

        self.spectrum_sim = Spectrum(x=x, y=y)
        self.spectrum_sim = self.spectrum_sim + self.background

    def CalcIobs(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    this is one of the main functions to partition the expt intensities
                        to overlapping peaks in the calculated pattern
        '''

        self.Iobs = {}
        for iph,p in enumerate(self.phases):

            self.Iobs[p] = {}

            for k,l in self.phases.wavelength.items():
                Ic = self.Icalc[p][k]

                tth = self.tth[p][k] + self.zero_error

                Iobs = []
                n = np.min((tth.shape[0],Ic.shape[0]))

                for i in range(n):
                    t = tth[i]
                    self.PseudoVoight(t)

                    y   = self.PV * Ic[i]
                    _,yo  = self.spectrum_expt.data
                    _,yc  = self.spectrum_sim.data

                    I = np.trapz(yo * y / yc, self.tth_list)
                    Iobs.append(I)

                self.Iobs[p][k] = np.array(Iobs)

    def calcRwp(self, params):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the weighted error between calculated and
                        experimental spectra. goodness of fit is also calculated. the 
                        weights are the inverse squareroot of the experimental intensities
        '''

        '''
        the err variable is the difference between simulated and experimental spectra
        '''
        for p in params:
            if(hasattr(self, p)):
                setattr(self, p, params[p].value)

        for p in self.phases:

            mat = self.phases[p]

            '''
            PART 1: update the lattice parameters
            '''
            lp = []

            pre = p + '_'
            if(pre+'a' in params):
                if(params[pre+'a'].vary):
                    lp.append(params[pre+'a'].value)
            if(pre+'b' in params):
                if(params[pre+'b'].vary):
                    lp.append(params[pre+'b'].value)
            if(pre+'c' in params):
                if(params[pre+'c'].vary):
                    lp.append(params[pre+'c'].value)
            if(pre+'alpha' in params):
                if(params[pre+'alpha'].vary):
                    lp.append(params[pre+'alpha'].value)
            if(pre+'beta' in params):
                if(params[pre+'beta'].vary):
                    lp.append(params[pre+'beta'].value)
            if(pre+'gamma' in params):
                if(params[pre+'gamma'].vary):
                    lp.append(params[pre+'gamma'].value)

            if(not lp):
                pass
            else:
                lp = self.phases[p].Required_lp(lp)
                self.phases[p].lparms = np.array(lp)
                self.phases[p]._calcrmt()
                self.calctth()

        self.computespectrum()

        self.err = (self.spectrum_sim - self.spectrum_expt)

        errvec = np.sqrt(self.weights * self.err._y**2)

        ''' weighted sum of square '''
        wss = np.trapz(self.weights * self.err._y**2, self.err._x)

        den = np.trapz(self.weights * self.spectrum_sim._y**2, self.spectrum_sim._x)

        ''' standard Rwp i.e. weighted residual '''
        Rwp = np.sqrt(wss/den)

        ''' number of observations to fit i.e. number of data points '''
        N = self.spectrum_sim._y.shape[0]

        ''' number of independent parameters in fitting '''
        P = len(params)
        Rexp = np.sqrt((N-P)/den)

        # Rwp and goodness of fit parameters
        self.Rwp = Rwp
        self.gofF = (Rwp / Rexp)**2

        return errvec

    def initialize_lmfit_parameters(self):

        params = lmfit.Parameters()

        for p in self.params:
            par = self.params[p]
            if(par.vary):
                params.add(p, value=par.value, min=par.lb, max = par.ub)

        return params

    def update_parameters(self):

        for p in self.res.params:
            par = self.res.params[p]
            self.params[p].value = par.value

    def RefineCycle(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    this is one refinement cycle for the least squares, typically few
                        10s to 100s of cycles may be required for convergence
        '''
        self.CalcIobs()
        self.Icalc = self.Iobs

        self.res = self.Refine()
        self.update_parameters()
        self.niter += 1
        self.Rwplist  = np.append(self.Rwplist, self.Rwp)
        self.gofFlist = np.append(self.gofFlist, self.gofF)
        print('Finished iteration. Rwp: {:.3f} % goodness of fit: {:.3f}'.format(self.Rwp*100., self.gofF))

    def Refine(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    this routine performs the least squares refinement for all variables
                        which are allowed to be varied.
        '''

        params = self.initialize_lmfit_parameters()

        fdict = {'ftol':1e-4, 'xtol':1e-4, 'gtol':1e-4, \
                 'verbose':0, 'max_nfev':8}

        fitter = lmfit.Minimizer(self.calcRwp, params)

        res = fitter.least_squares(**fdict)
        return res

    @property
    def Ul(self):
        return self._Ul

    @Ul.setter
    def Ul(self, Uinp):
        self._Ul = Uinp
        # self.computespectrum()
        return

    @property
    def Vl(self):
        return self._Vl

    @Vl.setter
    def Vl(self, Vinp):
        self._Vl = Vinp
        # self.computespectrum()
        return

    @property
    def Wl(self):
        return self._Wl

    @Wl.setter
    def Wl(self, Winp):
        self._Wl = Winp
        # self.computespectrum()
        return

    @property
    def Pl(self):
        return self._Pl

    @Pl.setter
    def Pl(self, Pinp):
        self._Pl = Pinp
        return

    @property
    def Xl(self):
        return self._Xl

    @Xl.setter
    def Xl(self, Xinp):
        self._Xl = Xinp
        return

    @property
    def Yl(self):
        return self._Yl

    @Yl.setter
    def Yl(self, Yinp):
        self._Yl = Yinp
        return

    @property
    def Ur(self):
        return self._Ur

    @Ur.setter
    def Ur(self, Uinp):
        self._Ur = Uinp
        return

    @property
    def Vr(self):
        return self._Vr

    @Vr.setter
    def Vr(self, Vinp):
        self._Vr = Vinp
        return

    @property
    def Wr(self):
        return self._Wr

    @Wr.setter
    def Wr(self, Winp):
        self._Wr = Winp
        return

    @property
    def Pr(self):
        return self._Pr

    @Pr.setter
    def Pr(self, Pinp):
        self._Pr = Pinp
        return

    @property
    def Xr(self):
        return self._Xr

    @Xr.setter
    def Xr(self, Xinp):
        self._Xr = Xinp
        return

    @property
    def Yr(self):
        return self._Yr

    @Yr.setter
    def Yr(self, Yinp):
        self._Yr = Yinp
        return

    @property
    def gamma(self):
        return self._gamma
    
    @gamma.setter
    def gamma(self, val):
        self._gamma = val

    @property
    def Hcag(self):
        return self._Hcag

    @Hcag.setter
    def Hcag(self, val):
        self._Hcag = val

    @property
    def eta1(self):
        return self._eta1

    @eta1.setter
    def eta1(self, val):
        self._eta1 = val
        return

    @property
    def eta2(self):
        return self._eta2

    @eta2.setter
    def eta2(self, val):
        self._eta2 = val
        return

    @property
    def eta3(self):
        return self._eta3

    @eta3.setter
    def eta3(self, val):
        self._eta3 = val
        return

    @property
    def tth_list(self):
        return self.spectrum_expt._x

    @property
    def zero_error(self):
        return self._zero_error
    
    @zero_error.setter
    def zero_error(self, value):
        self._zero_error = value
        return

class Material_Rietveld:

    def __init__(self, fhdf, xtal, dmin, kev):

        '''
        dmin in nm
        '''
        self.dmin = dmin.value

        '''
        voltage in ev
        '''
        self.voltage = kev.value * 1000.0

        self._readHDF(fhdf, xtal)
        self._calcrmt()

        if(self.aniU):
            self.calcBetaij()

        self.SYM_SG, self.SYM_PG_d, self.SYM_PG_d_laue, self.centrosymmetric, self.symmorphic = \
        symmetry.GenerateSGSym(self.sgnum, self.sgsetting)
        self.latticeType = symmetry.latticeType(self.sgnum)
        self.sg_hmsymbol = symbols.pstr_spacegroup[self.sgnum-1].strip()
        self.GenerateRecipPGSym()
        self.CalcMaxGIndex()
        self._calchkls()
        self.InitializeInterpTable()
        self.CalcWavelength()
        self.CalcPositions()

    def _readHDF(self, fhdf, xtal):

        # fexist = path.exists(fhdf)
        # if(fexist):
        fid = h5py.File(fhdf, 'r')
        xtal = "/"+xtal
        if xtal not in fid:
            raise IOError('crystal doesn''t exist in material file.')
        # else:
        #   raise IOError('material file does not exist.')

        gid         = fid.get(xtal)

        self.sgnum       = np.asscalar(np.array(gid.get('SpaceGroupNumber'), \
                                     dtype = np.int32))
        self.sgsetting = np.asscalar(np.array(gid.get('SpaceGroupSetting'), \
                                        dtype = np.int32))
        self.sgsetting -= 1
        """ 
            IMPORTANT NOTE:
            note that the latice parameters in EMsoft is nm by default
            hexrd on the other hand uses A as the default units, so we
            need to be careful and convert it right here, so there is no
            confusion later on
        """
        self.lparms      = list(gid.get('LatticeParameters'))

        # the last field in this is already
        self.atom_pos  = np.transpose(np.array(gid.get('AtomData'), dtype = np.float64))

        # the U factors are related to B by the relation B = 8pi^2 U
        self.U         = np.transpose(np.array(gid.get('U'), dtype = np.float64))

        self.aniU = False
        if(self.U.ndim > 1):
            self.aniU = True

        # read atom types (by atomic number, Z)
        self.atom_type = np.array(gid.get('Atomtypes'), dtype = np.int32)
        self.atom_ntype = self.atom_type.shape[0]

        fid.close()

    def calcBetaij(self):

        self.betaij = np.zeros([self.atom_ntype,3,3])
        for i in range(self.U.shape[0]):
            U = self.U[i,:]
            self.betaij[i,:,:] = np.array([[U[0], U[3], U[4]],\
                                         [U[3], U[1], U[5]],\
                                         [U[4], U[5], U[2]]])

            self.betaij[i,:,:] *= 2. * np.pi**2 * self.aij


    def CalcWavelength(self):
        # wavelength in nm
        self.wavelength =       constants.cPlanck * \
                            constants.cLight /  \
                            constants.cCharge / \
                            self.voltage
        self.wavelength *= 1e9
        self.CalcAnomalous()

    def CalcKeV(self):
        self.kev = constants.cPlanck * \
                   constants.cLight /  \
                   constants.cCharge / \
                   self.wavelength

        self.kev *= 1e-3

    def _calcrmt(self):

        a = self.lparms[0]
        b = self.lparms[1]
        c = self.lparms[2]

        alpha = np.radians(self.lparms[3])
        beta  = np.radians(self.lparms[4])
        gamma = np.radians(self.lparms[5])

        ca = np.cos(alpha);
        cb = np.cos(beta);
        cg = np.cos(gamma);
        sa = np.sin(alpha);
        sb = np.sin(beta);
        sg = np.sin(gamma);
        tg = np.tan(gamma);

        '''
            direct metric tensor
        '''
        self.dmt = np.array([[a**2, a*b*cg, a*c*cb],\
                             [a*b*cg, b**2, b*c*ca],\
                             [a*c*cb, b*c*ca, c**2]])
        self.vol = np.sqrt(np.linalg.det(self.dmt))

        if(self.vol < 1e-5):
            warnings.warn('unitcell volume is suspiciously small')

        '''
            reciprocal metric tensor
        '''
        self.rmt = np.linalg.inv(self.dmt)

        ast = self.CalcLength([1,0,0],'r')
        bst = self.CalcLength([0,1,0],'r')
        cst = self.CalcLength([0,0,1],'r')

        self.aij = np.array([[ast**2, ast*bst, ast*cst],\
                              [bst*ast, bst**2, bst*cst],\
                              [cst*ast, cst*bst, cst**2]])

    def _calchkls(self):
        self.hkls, self.multiplicity = self.getHKLs(self.dmin)

    ''' calculate dot product of two vectors in any space 'd' 'r' or 'c' '''
    def CalcLength(self, u, space):

        if(space =='d'):
            vlen = np.sqrt(np.dot(u, np.dot(self.dmt, u)))
        elif(space =='r'):
            vlen = np.sqrt(np.dot(u, np.dot(self.rmt, u)))
        elif(spec =='c'):
            vlen = np.linalg.norm(u)
        else:
            raise ValueError('incorrect space argument')

        return vlen

    def getTTh(self, wavelength):

        tth = []
        tth_mask = []
        for g in self.hkls:
            glen = self.CalcLength(g,'r')
            sth = glen*wavelength/2.
            if(np.abs(sth) <= 1.0):
                t = 2. * np.degrees(np.arcsin(sth))
                tth.append(t)
                tth_mask.append(True)
            else:
                tth_mask.append(False)

        tth = np.array(tth)
        tth_mask = np.array(tth_mask)
        return (tth,tth_mask)

    def GenerateRecipPGSym(self):

        self.SYM_PG_r = self.SYM_PG_d[0,:,:]
        self.SYM_PG_r = np.broadcast_to(self.SYM_PG_r,[1,3,3])
        self.SYM_PG_r_laue = self.SYM_PG_d[0,:,:]
        self.SYM_PG_r_laue = np.broadcast_to(self.SYM_PG_r_laue,[1,3,3])

        for i in range(1,self.SYM_PG_d.shape[0]):
            g = self.SYM_PG_d[i,:,:]
            g = np.dot(self.dmt, np.dot(g, self.rmt))
            g = np.round(np.broadcast_to(g,[1,3,3]))
            self.SYM_PG_r = np.concatenate((self.SYM_PG_r,g))

        for i in range(1,self.SYM_PG_d_laue.shape[0]):
            g = self.SYM_PG_d_laue[i,:,:]
            g = np.dot(self.dmt, np.dot(g, self.rmt))
            g = np.round(np.broadcast_to(g,[1,3,3]))
            self.SYM_PG_r_laue = np.concatenate((self.SYM_PG_r_laue,g))

        self.SYM_PG_r = self.SYM_PG_r.astype(np.int32)
        self.SYM_PG_r_laue = self.SYM_PG_r_laue.astype(np.int32)

    def CalcMaxGIndex(self):
        self.ih = 1
        while (1.0 / self.CalcLength(np.array([self.ih, 0, 0], dtype=np.float64), 'r') > self.dmin):
            self.ih = self.ih + 1
        self.ik = 1
        while (1.0 / self.CalcLength(np.array([0, self.ik, 0], dtype=np.float64), 'r') > self.dmin):
            self.ik = self.ik + 1
        self.il = 1
        while (1.0 / self.CalcLength(np.array([0, 0, self.il], dtype=np.float64),'r') > self.dmin):
            self.il = self.il + 1

    def CalcStar(self,v,space,applyLaue=False):
        '''
        this function calculates the symmetrically equivalent hkls (or uvws)
        for the reciprocal (or direct) point group symmetry.
        '''
        if(space == 'd'):
            if(applyLaue):
                sym = self.SYM_PG_d_laue
            else:
                sym = self.SYM_PG_d
        elif(space == 'r'):
            if(applyLaue):
                sym = self.SYM_PG_r_laue
            else:
                sym = self.SYM_PG_r
        else:
            raise ValueError('CalcStar: unrecognized space.')
        vsym = np.atleast_2d(v)
        for s in sym:
            vp = np.dot(s,v)
            # check if this is new
            isnew = True
            for vec in vsym:
                if(np.sum(np.abs(vp - vec)) < 1E-4):
                    isnew = False
                    break
            if(isnew):
                vsym = np.vstack((vsym, vp))
        return vsym

    def Allowed_HKLs(self, hkllist):
        '''
        this function checks if a particular g vector is allowed
        by lattice centering, screw axis or glide plane
        '''
        hkllist = np.atleast_2d(hkllist)
        centering = self.sg_hmsymbol[0]
        if(centering == 'P'):
            # all reflections are allowed
            mask = np.ones([hkllist.shape[0],],dtype=np.bool)
        elif(centering == 'F'):
            # same parity
            seo = np.sum(np.mod(hkllist+100,2),axis=1)
            mask = np.logical_not(np.logical_or(seo==1, seo==2))
        elif(centering == 'I'):
            # sum is even
            seo = np.mod(np.sum(hkllist,axis=1)+100,2)
            mask = (seo == 0)
            
        elif(centering == 'A'):
            # k+l is even
            seo = np.mod(np.sum(hkllist[:,1:3],axis=1)+100,2)
            mask = seo == 0
        elif(centering == 'B'):
            # h+l is even
            seo = np.mod(hkllist[:,0]+hkllist[:,2]+100,2)
            mask = seo == 0
        elif(centering == 'C'):
            # h+k is even
            seo = np.mod(hkllist[:,0]+hkllist[:,1]+100,2)
            mask = seo == 0
        elif(centering == 'R'):
            # -h+k+l is divisible by 3
            seo = np.mod(-hkllist[:,0]+hkllist[:,1]+hkllist[:,2]+90,3)
            mask = seo == 0
        else:
            raise RuntimeError('IsGAllowed: unknown lattice centering encountered.')
        hkls = hkllist[mask,:]

        if(not self.symmorphic):
            hkls = self.NonSymmorphicAbsences(hkls)
        return hkls.astype(np.int32)

    def omitscrewaxisabsences(self, hkllist, ax, iax):
        '''
        this function encodes the table on pg 48 of 
        international table of crystallography vol A
        the systematic absences due to different screw 
        axis is encoded here. 
        iax encodes the primary, secondary or tertiary axis
        iax == 0 : primary
        iax == 1 : secondary
        iax == 2 : tertiary
        @NOTE: only unique b axis in monoclinic systems 
        implemented as thats the standard setting
        '''
        if(self.latticeType == 'triclinic'):
            '''
                no systematic absences for the triclinic crystals
            '''
            pass
        elif(self.latticeType == 'monoclinic'):
            if(ax is not '2_1'):
                raise RuntimeError('omitscrewaxisabsences: monoclinic systems can only have 2_1 screw axis')
            '''
                only unique b-axis will be encoded
                it is the users responsibility to input 
                lattice parameters in the standard setting
                with b-axis having the 2-fold symmetry
            '''
            if(iax == 1):
                mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,2] == 0)
                mask2 = np.mod(hkllist[:,1]+100,2) != 0
                mask  = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            else:
                raise RuntimeError('omitscrewaxisabsences: only b-axis can have 2_1 screw axis')
        elif(self.latticeType == 'orthorhombic'):
            if(ax is not '2_1'):
                raise RuntimeError('omitscrewaxisabsences: orthorhombic systems can only have 2_1 screw axis')
            '''
            2_1 screw on primary axis
            h00 ; h = 2n
            '''
            if(iax == 0):
                mask1 = np.logical_and(hkllist[:,1] == 0,hkllist[:,2] == 0)
                mask2 = np.mod(hkllist[:,0]+100,2) != 0
                mask  = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(iax == 1):
                mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,2] == 0)
                mask2 = np.mod(hkllist[:,1]+100,2) != 0
                mask  = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(iax == 2):
                mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,1] == 0)
                mask2 = np.mod(hkllist[:,2]+100,2) != 0
                mask  = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
        elif(self.latticeType == 'tetragonal'):
            if(iax == 0):
                mask1 = np.logical_and(hkllist[:,0] == 0, hkllist[:,1] == 0)
                if(ax == '4_2'):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(ax in ['4_1','4_3']):
                    mask2 = np.mod(hkllist[:,2]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(iax == 1):
                mask1 = np.logical_and(hkllist[:,1] == 0, hkllist[:,2] == 0)
                mask2 = np.logical_and(hkllist[:,0] == 0, hkllist[:,2] == 0)
                if(ax == '2_1'):
                    mask3 = np.mod(hkllist[:,0]+100,2) != 0
                    mask4 = np.mod(hkllist[:,1]+100,2) != 0
                mask1 = np.logical_not(np.logical_and(mask1,mask3))
                mask2 = np.logical_not(np.logical_and(mask2,mask4))
                mask = ~np.logical_or(~mask1,~mask2)
                hkllist = hkllist[mask,:]
        elif(self.latticeType == 'trigonal'):
            mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,1] == 0)
            if(iax == 0):
                if(ax in ['3_1', '3_2']):
                    mask2 = np.mod(hkllist[:,2]+90,3) != 0
            else:
                raise RuntimeError('omitscrewaxisabsences: trigonal systems can only have screw axis')
            mask  = np.logical_not(np.logical_and(mask1,mask2))
            hkllist = hkllist[mask,:]
        elif(self.latticeType == 'hexagonal'):
            mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,1] == 0)
            if(iax == 0):
                if(ax is '6_3'):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(ax in['3_1','3_2','6_2','6_4']):
                    mask2 = np.mod(hkllist[:,2]+90,3) != 0
                elif(ax in ['6_1','6_5']):
                    mask2 = np.mod(hkllist[:,2]+120,6) != 0
            else:
                raise RuntimeError('omitscrewaxisabsences: hexagonal systems can only have screw axis')
            mask  = np.logical_not(np.logical_and(mask1,mask2))
            hkllist = hkllist[mask,:]
        elif(self.latticeType == 'cubic'):
            mask1 = np.logical_and(hkllist[:,0] == 0,hkllist[:,1] == 0)
            mask2 = np.logical_and(hkllist[:,0] == 0,hkllist[:,2] == 0)
            mask3 = np.logical_and(hkllist[:,1] == 0,hkllist[:,2] == 0)
            if(ax in ['2_1','4_2']):
                mask4 = np.mod(hkllist[:,2]+100,2) != 0
                mask5 = np.mod(hkllist[:,1]+100,2) != 0
                mask6 = np.mod(hkllist[:,0]+100,2) != 0
            elif(ax in ['4_1','4_3']):
                mask4 = np.mod(hkllist[:,2]+100,4) != 0
                mask5 = np.mod(hkllist[:,1]+100,4) != 0
                mask6 = np.mod(hkllist[:,0]+100,4) != 0
            mask1 = np.logical_not(np.logical_and(mask1,mask4))
            mask2 = np.logical_not(np.logical_and(mask2,mask5))
            mask3 = np.logical_not(np.logical_and(mask3,mask6))
            mask = ~np.logical_or(~mask1,np.logical_or(~mask2,~mask3))
            hkllist = hkllist[mask,:]
        return hkllist.astype(np.int32)

    def omitglideplaneabsences(self, hkllist, plane, ip):
        '''
        this function encodes the table on pg 47 of 
        international table of crystallography vol A
        the systematic absences due to different glide 
        planes is encoded here. 
        ip encodes the primary, secondary or tertiary plane normal
        ip == 0 : primary
        ip == 1 : secondary
        ip == 2 : tertiary
        @NOTE: only unique b axis in monoclinic systems 
        implemented as thats the standard setting
        '''
        if(self.latticeType == 'triclinic'):
            pass
        elif(self.latticeType == 'monoclinic'):
            if(ip == 1):
                mask1 = hkllist[:,1] == 0
                if(plane == 'c'):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(plane == 'a'):
                    mask2 = np.mod(hkllist[:,0]+100,2) != 0
                elif(plane == 'n'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,2]+100,2) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
        elif(self.latticeType == 'orthorhombic'):
            if(ip == 0):
                mask1 = hkllist[:,0] == 0
                if(plane == 'b'):
                    mask2 = np.mod(hkllist[:,1]+100,2) != 0
                elif(plane == 'c'):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(plane == 'n'):
                    mask2 = np.mod(hkllist[:,1]+hkllist[:,2]+100,2) != 0
                elif(plane == 'd'):
                    mask2 = np.mod(hkllist[:,1]+hkllist[:,2]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(ip == 1):
                mask1 = hkllist[:,1] == 0
                if(plane == 'c'):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(plane == 'a'):
                    mask2 = np.mod(hkllist[:,0]+100,2) != 0
                elif(plane == 'n'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,2]+100,2) != 0
                elif(plane == 'd'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,2]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(ip == 2):
                mask1 = hkllist[:,2] == 0
                if(plane == 'a'):
                    mask2 = np.mod(hkllist[:,0]+100,2) != 0
                elif(plane == 'b'):
                    mask2 = np.mod(hkllist[:,1]+100,2) != 0
                elif(plane == 'n'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,1]+100,2) != 0
                elif(plane == 'd'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,1]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
        elif(self.latticeType == 'tetragonal'):
            if(ip == 0):
                mask1 = hkllist[:,2] == 0
                if(plane == 'a'):
                    mask2 = np.mod(hkllist[:,0]+100,2) != 0
                elif(plane == 'b'):
                    mask2 = np.mod(hkllist[:,1]+100,2) != 0
                elif(plane == 'n'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,1]+100,2) != 0
                elif(plane == 'd'):
                    mask2 = np.mod(hkllist[:,0]+hkllist[:,1]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
            elif(ip == 1):
                mask1 = hkllist[:,0] == 0
                mask2 = hkllist[:,1] == 0
                if(plane in ['a','b']):
                    mask3 = np.mod(hkllist[:,1]+100,2) != 0
                    mask4 = np.mod(hkllist[:,0]+100,2) != 0
                elif(plane == 'c'):
                    mask3 = np.mod(hkllist[:,2]+100,2) != 0
                    mask4 = mask3
                elif(plane == 'n'):
                    mask3 = np.mod(hkllist[:,1]+hkllist[:,2]+100,2) != 0
                    mask4 = np.mod(hkllist[:,0]+hkllist[:,2]+100,2) != 0
                elif(plane == 'd'):
                    mask3 = np.mod(hkllist[:,1]+hkllist[:,2]+100,4) != 0
                    mask4 = np.mod(hkllist[:,0]+hkllist[:,2]+100,4) != 0
                mask1 = np.logical_not(np.logical_and(mask1,mask3))
                mask2 = np.logical_not(np.logical_and(mask2,mask4))
                mask = ~np.logical_or(~mask1,~mask2)
                hkllist = hkllist[mask,:]
            elif(ip == 2):
                mask1 = np.abs(hkllist[:,0]) == np.abs(hkllist[:,1])
                if(plane in ['c','n']):
                    mask2 = np.mod(hkllist[:,2]+100,2) != 0
                elif(plane == 'd'):
                    mask2 = np.mod(2*hkllist[:,0]+hkllist[:,2]+100,4) != 0
                mask = np.logical_not(np.logical_and(mask1,mask2))
                hkllist = hkllist[mask,:]
        elif(self.latticeType == 'trigonal'):
            if(plane is not 'c'):
                raise RuntimeError('omitglideplaneabsences: only c-glide allowed for trigonal systems')
            
            if(ip == 1):
                mask1 = hkllist[:,0] == 0
                mask2 = hkllist[:,1] == 0
                mask3 = hkllist[:,0] == -hkllist[:,1]
                if(plane == 'c'):
                    mask4 = np.mod(hkllist[:,2]+100,2) != 0
                else:
                    raise RuntimeError('omitglideplaneabsences: only c-glide allowed for trigonal systems')
            elif(ip == 2):
                mask1 = hkllist[:,1] == hkllist[:,0]
                mask2 = hkllist[:,0] == -2*hkllist[:,1]
                mask3 = -2*hkllist[:,0] == hkllist[:,1]
                if(plane == 'c'):
                    mask4 = np.mod(hkllist[:,2]+100,2) != 0
                else:
                    raise RuntimeError('omitglideplaneabsences: only c-glide allowed for trigonal systems')
            mask1 = np.logical_and(mask1,mask4)
            mask2 = np.logical_and(mask2,mask4)
            mask3 = np.logical_and(mask3,mask4)
            mask = np.logical_not(np.logical_or(mask1,np.logical_or(mask2,mask3)))
            hkllist = hkllist[mask,:]
        elif(self.latticeType == 'hexagonal'):
            if(plane is not 'c'):
                raise RuntimeError('omitglideplaneabsences: only c-glide allowed for hexagonal systems')
            if(ip == 2):
                mask1 = hkllist[:,0] == hkllist[:,1]
                mask2 = hkllist[:,0] == -2*hkllist[:,1]
                mask3 = -2*hkllist[:,0] == hkllist[:,1]
                mask4 = np.mod(hkllist[:,2]+100,2) != 0
                mask1 = np.logical_and(mask1,mask4)
                mask2 = np.logical_and(mask2,mask4)
                mask3 = np.logical_and(mask3,mask4)
                mask = np.logical_not(np.logical_or(mask1,np.logical_or(mask2,mask3)))
            elif(ip == 1):
                mask1 = hkllist[:,1] == 0
                mask2 = hkllist[:,0] == 0
                mask3 = hkllist[:,1] == -hkllist[:,0]
                mask4 = np.mod(hkllist[:,2]+100,2) != 0
            mask1 = np.logical_and(mask1,mask4)
            mask2 = np.logical_and(mask2,mask4)
            mask3 = np.logical_and(mask3,mask4)
            mask = np.logical_not(np.logical_or(mask1,np.logical_or(mask2,mask3)))
            hkllist = hkllist[mask,:]
        elif(self.latticeType == 'cubic'):
            if(ip == 0):
                mask1 = hkllist[:,0] == 0
                mask2 = hkllist[:,1] == 0
                mask3 = hkllist[:,2] == 0
                mask4 = np.mod(hkllist[:,0]+100,2) != 0
                mask5 = np.mod(hkllist[:,1]+100,2) != 0
                mask6 = np.mod(hkllist[:,2]+100,2) != 0
                if(plane  == 'a'):
                    mask1 = np.logical_or(np.logical_and(mask1,mask5),np.logical_and(mask1,mask6))
                    mask2 = np.logical_or(np.logical_and(mask2,mask4),np.logical_and(mask2,mask6))
                    mask3 = np.logical_and(mask3,mask4)
                    
                    mask = np.logical_not(np.logical_or(mask1,np.logical_or(mask2,mask3)))
                elif(plane == 'b'):
                    mask1 = np.logical_and(mask1,mask5)
                    mask3 = np.logical_and(mask3,mask5)
                    mask = np.logical_not(np.logical_or(mask1,mask3))
                elif(plane == 'c'):
                    mask1 = np.logical_and(mask1,mask6)
                    mask2 = np.logical_and(mask2,mask6)
                    mask = np.logical_not(np.logical_or(mask1,mask2))
                elif(plane == 'n'):
                    mask4 = np.mod(hkllist[:,1]+hkllist[:,2]+100,2) != 0
                    mask5 = np.mod(hkllist[:,0]+hkllist[:,2]+100,2) != 0
                    mask6 = np.mod(hkllist[:,0]+hkllist[:,1]+100,2) != 0
                    mask1 = np.logical_not(np.logical_and(mask1,mask4))
                    mask2 = np.logical_not(np.logical_and(mask2,mask5))
                    mask3 = np.logical_not(np.logical_and(mask3,mask6))
                    mask = ~np.logical_or(~mask1,np.logical_or(~mask2,~mask3))
                elif(plane == 'd'):
                    mask4 = np.mod(hkllist[:,1]+hkllist[:,2]+100,4) != 0
                    mask5 = np.mod(hkllist[:,0]+hkllist[:,2]+100,4) != 0
                    mask6 = np.mod(hkllist[:,0]+hkllist[:,1]+100,4) != 0
                    mask1 = np.logical_not(np.logical_and(mask1,mask4))
                    mask2 = np.logical_not(np.logical_and(mask2,mask5))
                    mask3 = np.logical_not(np.logical_and(mask3,mask6))
                    mask = ~np.logical_or(~mask1,np.logical_or(~mask2,~mask3))
                else:
                    raise RuntimeError('omitglideplaneabsences: unknown glide plane encountered.')
                hkllist = hkllist[mask,:]
            if(ip == 2):
                mask1 = np.abs(hkllist[:,0]) == np.abs(hkllist[:,1])
                mask2 = np.abs(hkllist[:,1]) == np.abs(hkllist[:,2])
                mask3 = np.abs(hkllist[:,0]) == np.abs(hkllist[:,2])
                if(plane in ['a','b','c','n']):
                    mask4 = np.mod(hkllist[:,2]+100,2) != 0
                    mask5 = np.mod(hkllist[:,0]+100,2) != 0
                    mask6 = np.mod(hkllist[:,1]+100,2) != 0
                elif(plane == 'd'):
                    mask4 = np.mod(2*hkllist[:,0]+hkllist[:,2]+100,4) != 0
                    mask5 = np.mod(hkllist[:,0]+2*hkllist[:,1]+100,4) != 0
                    mask6 = np.mod(2*hkllist[:,0]+hkllist[:,1]+100,4) != 0
                else:
                    raise RuntimeError('omitglideplaneabsences: unknown glide plane encountered.')
                mask1 = np.logical_not(np.logical_and(mask1,mask4))
                mask2 = np.logical_not(np.logical_and(mask2,mask5))
                mask3 = np.logical_not(np.logical_and(mask3,mask6))
                mask = ~np.logical_or(~mask1,np.logical_or(~mask2,~mask3))
                hkllist = hkllist[mask,:]
        return hkllist

    def NonSymmorphicAbsences(self, hkllist):
        '''
        this function prunes hkl list for the screw axis and glide 
        plane absences
        '''
        planes = constants.SYS_AB[self.sgnum][0]
        for ip,p in enumerate(planes):
            if(p is not ''):
                hkllist = self.omitglideplaneabsences(hkllist, p, ip)
        axes = constants.SYS_AB[self.sgnum][1]
        for iax,ax in enumerate(axes):
            if(ax is not ''):
                hkllist = self.omitscrewaxisabsences(hkllist, ax, iax)
        return hkllist

    def ChooseSymmetric(self, hkllist, InversionSymmetry=True):
        '''
        this function takes a list of hkl vectors and 
        picks out a subset of the list picking only one
        of the symmetrically equivalent one. The convention
        is to choose the hkl with the most positive components.
        '''
        mask = np.ones(hkllist.shape[0],dtype=np.bool)
        laue = InversionSymmetry
        for i,g in enumerate(hkllist):
            if(mask[i]):
                geqv = self.CalcStar(g,'r',applyLaue=laue)
                for r in geqv[1:,]:
                    rid = np.where(np.all(r==hkllist,axis=1))
                    mask[rid] = False
        hkl = hkllist[mask,:].astype(np.int32)
        hkl_max = []
        for g in hkl:
            geqv = self.CalcStar(g,'r',applyLaue=laue)
            loc = np.argmax(np.sum(geqv,axis=1))
            gmax = geqv[loc,:]
            hkl_max.append(gmax)
        return np.array(hkl_max).astype(np.int32)

    def SortHKL(self, hkllist):
        '''
        this function sorts the hkllist by increasing |g| 
        i.e. decreasing d-spacing. If two vectors are same 
        length, then they are ordered with increasing 
        priority to l, k and h
        '''
        glen = []
        for g in hkllist:
            glen.append(np.round(self.CalcLength(g,'r'),8))
        # glen = np.atleast_2d(np.array(glen,dtype=np.float)).T
        dtype = [('glen', float), ('max', int), ('sum', int), ('h', int), ('k', int), ('l', int)]
        a = []
        for i,gl in enumerate(glen):
            g = hkllist[i,:]
            a.append((gl, np.max(g), np.sum(g), g[0], g[1], g[2]))
        a = np.array(a, dtype=dtype)
        isort = np.argsort(a, order=['glen','max','sum','l','k','h'])
        return hkllist[isort,:]

    def getHKLs(self, dmin):
        '''
        this function generates the symetrically unique set of 
        hkls up to a given dmin.
        dmin is in nm
        '''
        '''
        always have the centrosymmetric condition because of
        Friedels law for xrays so only 4 of the 8 octants
        are sampled for unique hkls. By convention we will
        ignore all l < 0
        '''
        hmin = -self.ih-1
        hmax = self.ih
        kmin = -self.ik-1
        kmax = self.ik
        lmin = -1
        lmax = self.il
        hkllist = np.array([[ih, ik, il] for ih in np.arange(hmax,hmin,-1) \
                  for ik in np.arange(kmax,kmin,-1) \
                  for il in np.arange(lmax,lmin,-1)])
        hkl_allowed = self.Allowed_HKLs(hkllist)
        hkl = []
        dsp = []
        hkl_dsp = []
        for g in hkl_allowed:
            # ignore [0 0 0] as it is the direct beam
            if(np.sum(np.abs(g)) != 0):
                dspace = 1./self.CalcLength(g,'r')
                if(dspace >= dmin):
                    hkl_dsp.append(g)
        '''
        we now have a list of g vectors which are all within dmin range
        plus the systematic absences due to lattice centering and glide
        planes/screw axis has been taken care of
        the next order of business is to go through the list and only pick
        out one of the symetrically equivalent hkls from the list.
        '''
        hkl_dsp = np.array(hkl_dsp).astype(np.int32)
        '''
        the inversionsymmetry switch enforces the application of the inversion
        symmetry regradless of whether the crystal has the symmetry or not
        this is necessary in the case of xrays due to friedel's law
        '''
        hkl = self.ChooseSymmetric(hkl_dsp, InversionSymmetry=True)
        '''
        finally sort in order of decreasing dspacing
        '''
        hkls = self.SortHKL(hkl)

        multiplicity = []
        for g in hkls:
            multiplicity.append(self.CalcStar(g,'r').shape[0])

        multiplicity = np.array(multiplicity)
        return hkls, multiplicity

    def CalcPositions(self):
        '''
        calculate the asymmetric positions in the fundamental unitcell
        used for structure factor calculations
        '''
        numat = []
        asym_pos = []

        # using the wigner-seitz notation
        for i in range(self.atom_ntype):

            n = 1
            r = self.atom_pos[i,0:3]
            r = np.hstack((r, 1.))

            asym_pos.append(np.broadcast_to(r[0:3],[1,3]))
            
            for symmat in self.SYM_SG:
                # get new position
                rnew = np.dot(symmat, r)

                # reduce to fundamental unitcell with fractional
                # coordinates between 0-1
                rr = rnew[0:3]
                rr = np.modf(rr)[0]
                rr[rr < 0.] += 1.
                rr[np.abs(rr) < 1.0E-6] = 0.

                # check if this is new
                isnew = True
                for j in range(n):
                    if(np.sum(np.abs(rr - asym_pos[i][j,:])) < 1E-4):
                        isnew = False
                        break

                # if its new add this to the list
                if(isnew):
                    asym_pos[i] = np.vstack((asym_pos[i],rr))
                    n += 1

            numat.append(n)

        self.numat = np.array(numat)
        self.asym_pos = asym_pos

    def InitializeInterpTable(self):

        self.f1 = {}
        self.f2 = {}
        self.f_anam = {}

        fid = h5py.File(str(Path(__file__).resolve().parent)+'/Anomalous.h5','r')

        for i in range(0,self.atom_ntype):

            Z    = self.atom_type[i]
            elem = constants.ptableinverse[Z]
            gid = fid.get('/'+elem)
            data = gid.get('data')

            self.f1[elem] = interp1d(data[:,7], data[:,1])
            self.f2[elem] = interp1d(data[:,7], data[:,2])

        fid.close()

    def CalcAnomalous(self):

        for i in range(self.atom_ntype):

            Z = self.atom_type[i]
            elem = constants.ptableinverse[Z]
            f1 = self.f1[elem](self.wavelength)
            f2 = self.f2[elem](self.wavelength)
            frel = constants.frel[elem]
            Z = constants.ptable[elem]
            self.f_anam[elem] = np.complex(f1+frel-Z, f2)

    def CalcXRFormFactor(self, Z, s):

        '''
        we are using the following form factors for x-aray scattering:
        1. coherent x-ray scattering, f0 tabulated in Acta Cryst. (1995). A51,416-431
        2. Anomalous x-ray scattering (complex (f'+if")) tabulated in J. Phys. Chem. Ref. Data, 24, 71 (1995)
        and J. Phys. Chem. Ref. Data, 29, 597 (2000).
        3. Thompson nuclear scattering, fNT tabulated in Phys. Lett. B, 69, 281 (1977).

        the anomalous scattering is a complex number (f' + if"), where the two terms are given by
        f' = f1 + frel - Z
        f" = f2

        f1 and f2 have been tabulated as a function of energy in Anomalous.h5 in hexrd folder

        overall f = (f0 + f' + if" +fNT)
        '''
        elem = constants.ptableinverse[Z]
        sfact = constants.scatfac[elem]
        fe = sfact[5]
        fNT = constants.fNT[elem]
        frel = constants.frel[elem]
        f_anomalous = self.f_anam[elem]

        for i in range(5):
            fe += sfact[i] * np.exp(-sfact[i+6]*s)

        return (fe+fNT+f_anomalous)

    def CalcXRSF(self, hkl):

        '''
        the 1E-2 is to convert to A^-2
        since the fitting is done in those units
        '''
        s =  0.25 * self.CalcLength(hkl, 'r')**2 * 1E-2
        sf = np.complex(0.,0.)

        for i in range(0,self.atom_ntype):

            Z   = self.atom_type[i]
            ff  = self.CalcXRFormFactor(Z,s)

            if(self.aniU):
                T = np.exp(-np.dot(hkl,np.dot(self.betaij[i,:,:], hkl)))
            else:
                T = np.exp(-8.0*np.pi**2 * self.U[i]*s)

            ff *= self.atom_pos[i,3] * T

            for j in range(self.asym_pos[i].shape[0]):
                arg =  2.0 * np.pi * np.sum( hkl * self.asym_pos[i][j,:] )
                sf  = sf + ff * np.complex(np.cos(arg),-np.sin(arg))

        return np.abs(sf)**2

    def Required_lp(self, p):
        return _rqpDict[self.latticeType][1](p)

class Phases_Rietveld:
    ''' ======================================================================================================== 
        ======================================================================================================== 

    >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    >> @DATE:       05/20/2020 SS 1.0 original
    >> @DETAILS:    class to handle different phases in the LeBail fit. this is a stripped down
                    version of main Phase class for efficiency. only the components necessary for 
                    calculating peak positions are retained. further this will have a slight
                    modification to account for different wavelengths in the same phase name
        ======================================================================================================== 
        ======================================================================================================== 
    '''
    def _kev(x):
        return valWUnit('beamenergy','energy', x,'keV')

    def _nm(x):
        return valWUnit('lp', 'length', x, 'nm')

    def __init__(self, material_file=None, 
                 material_keys=None,
                 dmin = _nm(0.05),
                 wavelength={'alpha1':[_nm(0.15406),1.],'alpha2':[_nm(0.154443),0.52]}
                 ):

        self.phase_dict = {}
        self.num_phases = 0
        self.wavelength = wavelength
        self.dmin = dmin

        if(material_file is not None):
            if(material_keys is not None):
                if(type(material_keys) is not list):
                    self.add(material_file, material_keys)
                else:
                    self.add_many(material_file, material_keys)

    def __str__(self):
        resstr = 'Phases in calculation:\n'
        for i,k in enumerate(self.phase_dict.keys()):
            resstr += '\t'+str(i+1)+'. '+k+'\n'
        return resstr

    def __getitem__(self, key):
        if(key in self.phase_dict.keys()):
            return self.phase_dict[key]
        else:
            raise ValueError('phase with name not found')

    def __setitem__(self, key, mat_cls):

        if(key in self.phase_dict.keys()):
            warnings.warn('phase already in parameter list. overwriting ...')
        # if(isinstance(mat_cls, Material_Rietveld)):
        self.phase_dict[key] = mat_cls
        # else:
            # raise ValueError('input not a material class')

    def __iter__(self):
        self.n = 0
        return self

    def __next__(self):
        if(self.n < len(self.phase_dict.keys())):
            res = list(self.phase_dict.keys())[self.n]
            self.n += 1
            return res
        else:
            raise StopIteration

    def __len__(self):
         return len(self.phase_dict)

    def add(self, material_file, material_key):
        self[material_key] = {}
        for l in self.wavelength:
            lam = self.wavelength[l][0].value * 1e-9
            E = constants.cPlanck * constants.cLight / constants.cCharge / lam
            E *= 1e-3
            kev = valWUnit('beamenergy','energy', E,'keV')
            self[material_key][l] = Material_Rietveld(material_file, material_key, dmin=self.dmin, kev=kev)

    def add_many(self, material_file, material_keys):
        
        for k in material_keys:
            self[k] = {}
            self.num_phases += 1
            for l in self.wavelength:
                lam = self.wavelength[l][0].value * 1e-9
                E = constants.cPlanck * constants.cLight / constants.cCharge / lam
                E *= 1e-3
                kev = valWUnit('beamenergy','energy', E,'keV')
                self[k][l] = Material_Rietveld(material_file, k, dmin=self.dmin, kev=kev)


        for k in self:
            for l in self.wavelength:
                self[k][l].pf = 1.0/self.num_phases

        self.material_file = material_file
        self.material_keys = material_keys

    def load(self, fname):
        '''
            >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
            >> @DATE:       06/08/2020 SS 1.0 original
            >> @DETAILS:    load parameters from yaml file
        '''
        with open(fname) as file:
            dic = yaml.load(file, Loader=yaml.FullLoader)

        for mfile in dic.keys():
            mat_keys = list(dic[mfile])
            self.add_many(mfile, mat_keys)

    def dump(self, fname):
        '''
            >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
            >> @DATE:       06/08/2020 SS 1.0 original
            >> @DETAILS:    dump parameters to yaml file
        '''
        dic = {}
        k = self.material_file
        dic[k] =  [m for m in self]

        with open(fname, 'w') as f:
            data = yaml.dump(dic, f, sort_keys=False)

class Rietveld:
    ''' ======================================================================================================== 
    ======================================================================================================== 

    >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    >> @DATE:       01/08/2020 SS 1.0 original
                    07/13/2020 SS 2.0 complete rewrite to include new parameter/material/pattern class

    >> @DETAILS:    this is the main rietveld class and contains all the refinable parameters
                    for the analysis. the member classes are as follows (in order of initialization):

                    1. Spectrum         contains the experimental spectrum
                    2. Background       contains the background extracted from spectrum
                    3. Refine           contains all the machinery for refinement
        ======================================================================================================== 
        ======================================================================================================== 
    '''
    def __init__(self,expt_file=None,param_file=None,phase_file=None,wavelength=None):


        self.initialize_expt_spectrum(expt_file)
        self._tstart = time.time()
        if(wavelength is not None):
            self.wavelength = wavelength
        self.initialize_phases(phase_file)
        self.initialize_parameters(param_file)

        self.PolarizationFactor()
        self.computespectrum()

        self._tstop = time.time()
        self.tinit = self._tstop - self._tstart

        self.niter = 0
        self.Rwplist  = np.empty([0])
        self.gofFlist = np.empty([0])

    def __str__(self):
        resstr = '<Rietveld Fit class>\nParameters of the model are as follows:\n'
        resstr += self.params.__str__()
        return resstr

    def initialize_parameters(self, param_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >>              07/15/2020 SS 1.1 modified to add lattice parameters, atom positions
                        and isotropic DW factors
        >> @DETAILS:    initialize parameter list from file. if no file given, then initialize
                        to some default values (lattice constants are for CeO2)
        '''
        params = Parameters()
        if(param_file is not None):
            if(path.exists(param_file)):
                params.load(param_file)
                '''
                this part initializes the lattice parameters, atom positions in asymmetric 
                unit, occupation and the isotropic debye waller factor. the anisotropic DW 
                factors will be added in the future
                '''
                for p in self.phases:
                    l = list(self.phases[p].keys())[0]

                    mat = self.phases[p][l] 
                    lp       = np.array(mat.lparms)
                    rid      = list(_rqpDict[mat.latticeType][0])

                    lp       = lp[rid]
                    name     = _lpname[rid]

                    for n,l in zip(name,lp):
                        nn = p+'_'+n
                        '''
                        is l is small, it is one of the length units
                        else it is an angle
                        '''
                        if(l < 10.):
                            params.add(nn,value=l,lb=l-0.05,ub=l+0.05,vary=False)
                        else:
                            params.add(nn,value=l,lb=l-1.,ub=l+1.,vary=False)

                    atom_pos   = mat.atom_pos[:,0:3]
                    occ        = mat.atom_pos[:,3]
                    atom_type  = mat.atom_type

                    atom_label = _getnumber(atom_type)
                    self.atom_label = atom_label

                    for i in range(atom_type.shape[0]):

                        Z = atom_type[i]
                        elem = constants.ptableinverse[Z]
                        
                        nn = p+'_'+elem+str(atom_label[i])+'_x'
                        params.add(nn,value=atom_pos[i,0],lb=0.0,ub=1.0,vary=False)

                        nn = p+'_'+elem+str(atom_label[i])+'_y'
                        params.add(nn,value=atom_pos[i,1],lb=0.0,ub=1.0,vary=False)

                        nn = p+'_'+elem+str(atom_label[i])+'_z'
                        params.add(nn,value=atom_pos[i,2],lb=0.0,ub=1.0,vary=False)

                        nn = p+'_'+elem+str(atom_label[i])+'_occ'
                        params.add(nn,value=occ[i],lb=0.0,ub=1.0,vary=False)

                        if(mat.aniU):
                            U = mat.U
                            for j in range(6):
                                nn = p+'_'+elem+str(atom_label[i])+'_'+_nameU[j]
                                params.add(nn,value=U[i,j],lb=-1e-3,ub=np.inf,vary=False)
                        else:

                            nn = p+'_'+elem+str(atom_label[i])+'_dw'
                            params.add(nn,value=mat.U[i],lb=0.0,ub=np.inf,vary=False)

            else:
                raise FileError('parameter file doesn\'t exist.')
        else:
            '''
                first 6 are the lattice paramaters
                next three are cagliotti parameters
                next are the three gauss+lorentz mixing paramters
                final is the zero instrumental peak position error
            '''
            names   = ('a','b','c','alpha','beta','gamma',\
                      'U','V','W','eta1','eta2','eta3','tth_zero',\
                      'scale')
            values  = (5.415, 5.415, 5.415, 90., 90., 90., \
                        0.5, 0.5, 0.5, 1e-3, 1e-3, 1e-3, 0., \
                        1.0)

            lbs         = (-np.Inf,) * len(names)
            ubs         = (np.Inf,)  * len(names)
            varies  = (False,)   * len(names)

            params.add_many(names,values=values,varies=varies,lbs=lbs,ubs=ubs)

        self.params = params

        self._scale = self.params['scale'].value
        self._U = self.params['U'].value
        self._V = self.params['V'].value
        self._W = self.params['W'].value
        self._P = self.params['P'].value
        self._X = self.params['X'].value
        self._Y = self.params['Y'].value
        self._eta1 = self.params['eta1'].value
        self._eta2 = self.params['eta2'].value
        self._eta3 = self.params['eta3'].value
        self._zero_error = self.params['zero_error'].value

    '''
        no params are varied
    '''
    def params_vary_off(self):

        for p in self.params:
            self.params[p].vary = False

    '''
            all params are varied
    '''
    def params_vary_on(self):

        for p in self.params:
            self.params[p].vary = True

    '''
        turn all cagliotti parameters on
    '''
    def params_cagliotti_vary_on(self):
        self.params['U'].vary = True
        self.params['V'].vary = True
        self.params['W'].vary = True

    '''
        turn all cagliotti parameters off
    '''
    def params_cagliotti_vary_off(self):
        self.params['U'].vary = False
        self.params['V'].vary = False
        self.params['W'].vary = False

    '''
        turn all mixing parameters on
    '''
    def params_eta_vary_on(self):
        self.params['eta1'].vary = True
        self.params['eta2'].vary = True
        self.params['eta3'].vary = True

    '''
        turn all mixing parameters off
    '''
    def params_eta_vary_on(self):
        self.params['eta1'].vary = False
        self.params['eta2'].vary = False
        self.params['eta3'].vary = False

    '''
        turn all lattice paramater on
    '''
    def params_lp_vary_all_on(self):

        for p in self.phases:

            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l] 
            rid      = list(_rqpDict[mat.latticeType][0])
            name     = _lpname[rid]
            for n in name:
                nn = p+'_'+n
                self.params[nn].vary = True

    '''
        turn all lattice paramater off
    '''
    def params_lp_vary_all_off(self):

        for p in self.phases:

            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l] 
            rid      = list(_rqpDict[mat.latticeType][0])
            name     = _lpname[rid]
            for n in name:
                nn = p+'_'+n
                self.params[nn].vary = False

    '''
        turn lattice paramater for a phase on
    '''
    def params_lp_vary_phase_on(self, phase_name):

        l = list(self.phases[phase_name].keys())[0]
        mat = self.phases[phase_name][l] 
        rid      = list(_rqpDict[mat.latticeType][0])
        name     = _lpname[rid]
        for n in name:
            nn = phase_name+'_'+n
            self.params[nn].vary = True

    '''
        turn lattice paramater for a phase off
    '''
    def params_lp_vary_phase_off(self, phase_name):

        l = list(self.phases[phase_name].keys())[0]
        mat = self.phases[phase_name][l] 
        rid      = list(_rqpDict[mat.latticeType][0])
        name     = _lpname[rid]
        for n in name:
            nn = phase_name+'_'+n
            self.params[nn].vary = False

    '''
        turn all the debye waller factors on
    '''
    def params_U_vary_all_on(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                if(mat.aniU):
                    U = mat.U
                    for j in range(6):
                        nn = p+'_'+elem+str(self.atom_label[i])+'_'+_nameU[j]
                        self.params[nn].vary = True
                else:

                    nn = p+'_'+elem+str(self.atom_label[i])+'_dw'
                    self.params[nn].vary = True

    '''
        turn all the debye waller factors on
    '''
    def params_U_vary_all_off(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                if(mat.aniU):
                    U = mat.U
                    for j in range(6):
                        nn = p+'_'+elem+str(self.atom_label[i])+'_'+_nameU[j]
                        self.params[nn].vary = False
                else:

                    nn = p+'_'+elem+str(self.atom_label[i])+'_dw'
                    self.params[nn].vary = False

    '''
        turn all the debye waller factors 
        for an atom label off
    '''
    def params_U_vary_label_off(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                if(mat.aniU):
                    U = mat.U
                    for j in range(6):
                        nn = p+'_'+label+'_'+_nameU[j]
                        self.params[nn].vary = False
                else:
                    nn = p+'_'+label+'_dw'
                    self.params[nn].vary = False
            else:
                raise ValueError('element not present any of the phases')

    '''
        turn all the debye waller factors 
        for an atom label on
    '''
    def params_U_vary_label_on(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                if(mat.aniU):
                    U = mat.U
                    for j in range(6):
                        nn = p+'_'+label+'_'+_nameU[j]
                        self.params[nn].vary = True
                else:
                    nn = p+'_'+label+'_dw'
                    self.params[nn].vary = True
            else:
                raise ValueError('element not present any of the phases')

    '''
        turn all the occupation factors on
    '''
    def params_occ_vary_all_on(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                nn = p+'_'+elem+str(self.atom_label[i])+'_occ'
                self.params[nn].vary = True

    '''
        turn all the occupation factors on
    '''
    def params_occ_vary_all_off(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                nn = p+'_'+elem+str(self.atom_label[i])+'_occ'
                self.params[nn].vary = False

    '''
        turn all the occupation factors 
        for an atom label off
    '''
    def params_occ_vary_label_off(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                nn = p+'_'+label+'_occ'
                self.params[nn].vary = False
            else:
                raise ValueError('element not present any of the phases')

    '''
        turn all the occupation factors 
        for an atom label on
    '''
    def params_occ_vary_label_on(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                nn = p+'_'+label+'_occ'
                self.params[nn].vary = True
            else:
                raise ValueError('element not present any of the phases')

    '''
        turn all the atom positions factors on
    '''
    def params_xyz_vary_all_on(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                nn = p+'_'+elem+str(self.atom_label[i])+'_x'
                self.params[nn].vary = True
                nn = p+'_'+elem+str(self.atom_label[i])+'_y'
                self.params[nn].vary = True
                nn = p+'_'+elem+str(self.atom_label[i])+'_z'
                self.params[nn].vary = True

    '''
        turn all the atom positions factors on
    '''
    def params_xyz_vary_all_off(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                nn = p+'_'+elem+str(self.atom_label[i])+'_x'
                self.params[nn].vary = False
                nn = p+'_'+elem+str(self.atom_label[i])+'_y'
                self.params[nn].vary = False
                nn = p+'_'+elem+str(self.atom_label[i])+'_z'
                self.params[nn].vary = False

    '''
        turn all the atom positions
        for an atom label off
    '''
    def params_xyz_vary_label_off(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                nn = p+'_'+label+'_x'
                self.params[nn].vary = False
                nn = p+'_'+label+'_y'
                self.params[nn].vary = False
                nn = p+'_'+label+'_z'
                self.params[nn].vary = False
            else:
                raise ValueError('element not present any of the phases')

    '''
        turn all the atom positions
        for an atom label on
    '''
    def params_xyz_vary_label_on(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                nn = p+'_'+label+'_x'
                self.params[nn].vary = True
                nn = p+'_'+label+'_y'
                self.params[nn].vary = True
                nn = p+'_'+label+'_z'
                self.params[nn].vary = True
            else:
                raise ValueError('element not present any of the phases')

    def initialize_expt_spectrum(self, expt_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    load the experimental spectum of 2theta-intensity
        '''
        # self.spectrum_expt = Spectrum.from_file()
        if(expt_file is not None):
            if(path.exists(expt_file)):
                self.spectrum_expt = Spectrum.from_file(expt_file,skip_rows=0)
                self.tth_max = np.amax(self.spectrum_expt._x)
                self.tth_min = np.amin(self.spectrum_expt._x)

                ''' also initialize statistical weights for the error calculation'''
                self.weights = 1.0 / np.sqrt(self.spectrum_expt.y)
                self.initialize_bkg()
            else:
                raise FileError('input spectrum file doesn\'t exist.')

    def initialize_bkg(self):

        '''
            the cubic spline seems to be the ideal route in terms
            of determining the background intensity. this involves 
            selecting a small (~5) number of points from the spectrum,
            usually called the anchor points. a cubic spline interpolation
            is performed on this subset to estimate the overall background.
            scipy provides some useful routines for this
        '''
        self.selectpoints()
        x = self.points[:,0]
        y = self.points[:,1]
        self.splinefit(x, y)

    def selectpoints(self):

        fig = plt.figure()
        ax = fig.add_subplot(111)
        ax.set_title('Select 5 points for background estimation')

        line = ax.plot(self.tth_list, self.spectrum_expt._y, '-b', picker=7)  # 5 points tolerance
        plt.show()

        self.points = np.asarray(plt.ginput(7,timeout=-1, show_clicks=True))
        plt.close()

    # cubic spline fit of background using custom points chosen from plot
    def splinefit(self, x, y):
        cs = CubicSpline(x,y)
        bkg = cs(self.tth_list)
        self.background = Spectrum(x=self.tth_list, y=bkg)

    def initialize_phases(self, phase_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    load the phases for the LeBail fits
        '''
        p = Phases_Rietveld(wavelength=self.wavelength)
        if(phase_file is not None):
            if(path.exists(phase_file)):
                p.load(phase_file)
            else:
                raise FileError('phase file doesn\'t exist.')
        self.phases = p

        self.calctth()
        self.calcsf()

    def calctth(self):
        self.tth = {}
        for p in self.phases:
            self.tth[p] = {}
            for k,l in self.phases.wavelength.items():
                t,_ = self.phases[p][k].getTTh(l[0].value)
                limit = np.logical_and(t >= self.tth_min,\
                                       t <= self.tth_max)
                self.tth[p][k] = t[limit]

    def calcsf(self):
        self.sf = {}
        for p in self.phases:
            self.sf[p] = {}
            for k,l in self.phases.wavelength.items():
                w_int = l[1]
                t,tmask = self.phases[p][k].getTTh(l[0].value)
                limit = np.logical_and(t >= self.tth_min,\
                                       t <= self.tth_max)
                hkl = self.phases[p][k].hkls[tmask][limit]
                multiplicity = self.phases[p][k].multiplicity[tmask][limit]
                sf = []
                for m,g in zip(multiplicity,hkl):
                    sf.append(w_int * m * self.phases[p][k].CalcXRSF(g))
                self.sf[p][k] = np.array(sf)

    def CagliottiH(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    calculates the cagiotti parameter for the peak width
        '''
        th          = np.radians(0.5*tth)
        tanth       = np.tan(th)
        cth         = np.cos(th)
        Hsq         = self.U * tanth**2 + self.V * tanth + self.W
        if(Hsq < 0.):
            Hsq = 1.0e-12
        self.Hcag   = np.sqrt(Hsq)

    def LorentzH(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       07/20/2020 SS 1.0 original
        >> @DETAILS:    calculates the size and strain broadening for Lorentzian peak
        '''
        th = np.radians(0.5*tth)
        tanth       = np.tan(th)
        cth         = np.cos(th)
        self.gamma = self.X / cth + self.Y * tanth

    def MixingFact(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    calculates the mixing factor eta
        '''
        self.eta = self.eta1 + self.eta2 * tth + self.eta3 * (tth)**2

        if(self.eta > 1.0):
            self.eta = 1.0

        elif(self.eta < 0.0):
            self.eta = 0.0

    def Gaussian(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the gaussian peak profile
        '''

        H  = self.Hcag
        cg = 4.*np.log(2.)
        self.GaussianI = (np.sqrt(cg/np.pi)/H) * np.exp( -cg * ((self.tth_list - tth)/H)**2 )

    def Lorentzian(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the lorentzian peak profile
        '''

        H = self.Hcag
        cl = 4.
        self.LorentzI = (2./np.pi/H) / ( 1. + cl*((self.tth_list - tth)/H)**2)

    def PseudoVoight(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the pseudo-voight function as weighted 
                        average of gaussian and lorentzian
        '''

        self.CagliottiH(tth)
        self.Gaussian(tth)
        self.LorentzH(tth)
        self.Lorentzian(tth)
        self.MixingFact(tth)

        self.PV = self.eta * self.GaussianI + \
                  (1.0 - self.eta) * self.LorentzI

    def PolarizationFactor(self):

        tth = np.radians(self.tth_list)
        self.LP = (1 + np.cos(tth)**2)/ \
        np.cos(0.5*tth)/np.sin(0.5*tth)**2

    def computespectrum(self):

        I = np.zeros(self.tth_list.shape)
        for p in self.tth:
            for l in self.tth[p]:

                tth = self.tth[p][l]
                sf  = self.sf[p][l]
                pf = self.phases[p][l].pf / self.phases[p][l].vol**2

                for t,fsq in zip(tth,sf):
                    self.PseudoVoight(t+self.zero_error)
                    I += self.scale * pf * self.PV * fsq * self.LP

        self.spectrum_sim = Spectrum(self.tth_list, I) + self.background

    def calcRwp(self, params):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the weighted error between calculated and
                        experimental spectra. goodness of fit is also calculated. the 
                        weights are the inverse squareroot of the experimental intensities
        '''

        '''
        the err variable is the difference between simulated and experimental spectra
        '''
        for p in params:
            if(hasattr(self, p)):
                setattr(self, p, params[p].value)

        self.updated_lp = False
        self.updated_atominfo = False
        for p in self.phases:
            for l in self.phases[p]:

                mat = self.phases[p][l]

                '''
                PART 1: update the lattice parameters
                '''
                lp = []

                pre = p + '_'
                if(pre+'a' in params):
                    if(params[pre+'a'].vary):
                        lp.append(params[pre+'a'].value)
                if(pre+'b' in params):
                    if(params[pre+'b'].vary):
                        lp.append(params[pre+'b'].value)
                if(pre+'c' in params):
                    if(params[pre+'c'].vary):
                        lp.append(params[pre+'c'].value)
                if(pre+'alpha' in params):
                    if(params[pre+'alpha'].vary):
                        lp.append(params[pre+'alpha'].value)
                if(pre+'beta' in params):
                    if(params[pre+'beta'].vary):
                        lp.append(params[pre+'beta'].value)
                if(pre+'gamma' in params):
                    if(params[pre+'gamma'].vary):
                        lp.append(params[pre+'gamma'].value)

                if(not lp):
                    pass
                else:
                    lp = self.phases[p][l].Required_lp(lp)
                    self.phases[p][l].lparms = np.array(lp)
                    self.updated_lp = True
                '''
                PART 2: update the atom info
                '''

                atom_type = mat.atom_type

                for i in range(atom_type.shape[0]):

                    Z = atom_type[i]
                    elem = constants.ptableinverse[Z]
                    nx = p+'_'+elem+str(self.atom_label[i])+'_x'
                    ny = p+'_'+elem+str(self.atom_label[i])+'_y'
                    nz = p+'_'+elem+str(self.atom_label[i])+'_z'
                    oc = p+'_'+elem+str(self.atom_label[i])+'_occ'

                    if(mat.aniU):
                        Un = []
                        for j in range(6):
                            Un.append(p+'_'+elem+str(self.atom_label[i])+'_'+_nameU[j])
                    else:
                        dw = p+'_'+elem+str(self.atom_label[i])+'_dw'

                    if(nx in params):
                        x = params[nx].value
                        self.updated_atominfo = True
                    else:
                        x = self.params[nx].value

                    if(ny in params):
                        y = params[ny].value
                        self.updated_atominfo = True
                    else:
                        y = self.params[ny].value

                    if(nz in params):
                        z = params[nz].value
                        self.updated_atominfo = True
                    else:
                        z = self.params[nz].value

                    if(oc in params):
                        oc = params[oc].value
                        self.updated_atominfo = True
                    else:
                        oc = self.params[oc].value

                    if(mat.aniU):
                        U = []
                        for j in range(6):
                            if(Un[j] in params):
                                self.updated_atominfo = True
                                U.append(params[Un[j]].value)
                            else:
                                U.append(self.params[Un[j]].value)
                        U = np.array(U)
                        mat.U[i,:] = U
                    else:
                        if(dw in params):
                            dw = params[dw].value
                            self.updated_atominfo = True
                        else:
                            dw = self.params[dw].value
                        mat.U[i] = dw

                    mat.atom_pos[i,:] = np.array([x,y,z,oc])

                if(mat.aniU):
                    mat.calcBetaij()
                if(self.updated_lp):
                    mat._calcrmt()

        if(self.updated_lp):
            self.calctth()
        if(self.updated_lp or self.updated_atominfo):
            self.calcsf()

        self.computespectrum()

        self.err = (self.spectrum_sim - self.spectrum_expt)

        errvec = np.sqrt(self.weights * self.err._y**2)

        ''' weighted sum of square '''
        wss = np.trapz(self.weights * self.err._y**2, self.err._x)

        den = np.trapz(self.weights * self.spectrum_sim._y**2, self.spectrum_sim._x)

        ''' standard Rwp i.e. weighted residual '''
        Rwp = np.sqrt(wss/den)

        ''' number of observations to fit i.e. number of data points '''
        N = self.spectrum_sim._y.shape[0]

        ''' number of independent parameters in fitting '''
        P = len(params)
        Rexp = np.sqrt((N-P)/den)

        # Rwp and goodness of fit parameters
        self.Rwp = Rwp
        self.gofF = (Rwp / Rexp)**2

        return errvec

    def initialize_lmfit_parameters(self):

        params = lmfit.Parameters()

        for p in self.params:
            par = self.params[p]
            if(par.vary):
                params.add(p, value=par.value, min=par.lb, max = par.ub)

        return params

    def update_parameters(self):

        for p in self.res.params:
            par = self.res.params[p]
            self.params[p].value = par.value

    def Refine(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    this routine performs the least squares refinement for all variables
                        which are allowed to be varied.
        '''

        params = self.initialize_lmfit_parameters()

        fdict = {'ftol':1e-4, 'xtol':1e-4, 'gtol':1e-4, \
                 'verbose':0, 'max_nfev':8}

        fitter = lmfit.Minimizer(self.calcRwp, params)

        self.res = fitter.least_squares(**fdict)

        self.update_parameters()

        self.niter += 1
        self.Rwplist  = np.append(self.Rwplist, self.Rwp)
        self.gofFlist = np.append(self.gofFlist, self.gofF)

        print('Finished iteration. Rwp: {:.3f} % goodness of fit: {:.3f}'.format(self.Rwp*100., self.gofF))

    @property
    def U(self):
        return self._U

    @U.setter
    def U(self, Uinp):
        self._U = Uinp
        return

    @property
    def V(self):
        return self._V

    @V.setter
    def V(self, Vinp):
        self._V = Vinp
        return

    @property
    def W(self):
        return self._W

    @W.setter
    def W(self, Winp):
        self._W = Winp
        return

    @property
    def P(self):
        return self._P

    @P.setter
    def P(self, Pinp):
        self._P = Pinp
        return

    @property
    def X(self):
        return self._X

    @X.setter
    def X(self, Xinp):
        self._X = Xinp
        return

    @property
    def Y(self):
        return self._Y

    @Y.setter
    def Y(self, Yinp):
        self._Y = Yinp
        return

    @property
    def gamma(self):
        return self._gamma
    
    @gamma.setter
    def gamma(self, val):
        self._gamma = val

    @property
    def Hcag(self):
        return self._Hcag

    @Hcag.setter
    def Hcag(self, val):
        self._Hcag = val

    @property
    def eta1(self):
        return self._eta1

    @eta1.setter
    def eta1(self, val):
        self._eta1 = val
        return

    @property
    def eta2(self):
        return self._eta2

    @eta2.setter
    def eta2(self, val):
        self._eta2 = val
        return

    @property
    def eta3(self):
        return self._eta3

    @eta3.setter
    def eta3(self, val):
        self._eta3 = val
        return

    @property
    def tth_list(self):
        return self.spectrum_expt._x

    @property
    def zero_error(self):
        return self._zero_error
    
    @zero_error.setter
    def zero_error(self, value):
        self._zero_error = value
        return

    @property
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, value):
        self._scale = value
        return

class Rietveld_Asym:
    ''' ======================================================================================================== 
    ======================================================================================================== 

    >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
    >> @DATE:       01/08/2020 SS 1.0 original
                    07/13/2020 SS 2.0 complete rewrite to include new parameter/material/pattern class

    >> @DETAILS:    this is the main rietveld class and contains all the refinable parameters
                    for the analysis. the member classes are as follows (in order of initialization):

                    1. Spectrum         contains the experimental spectrum
                    2. Background       contains the background extracted from spectrum
                    3. Refine           contains all the machinery for refinement
        ======================================================================================================== 
        ======================================================================================================== 
    '''
    def __init__(self,expt_file=None,param_file=None,phase_file=None,wavelength=None):


        self.initialize_expt_spectrum(expt_file)
        self._tstart = time.time()
        if(wavelength is not None):
            self.wavelength = wavelength
        self.initialize_phases(phase_file)
        self.initialize_parameters(param_file)

        self.PolarizationFactor()
        self.computespectrum()

        self._tstop = time.time()
        self.tinit = self._tstop - self._tstart

        self.niter = 0
        self.Rwplist  = np.empty([0])
        self.gofFlist = np.empty([0])

    def __str__(self):
        resstr = '<Rietveld Fit class>\nParameters of the model are as follows:\n'
        resstr += self.params.__str__()
        return resstr

    def initialize_parameters(self, param_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >>              07/15/2020 SS 1.1 modified to add lattice parameters, atom positions
                        and isotropic DW factors
        >> @DETAILS:    initialize parameter list from file. if no file given, then initialize
                        to some default values (lattice constants are for CeO2)
        '''
        params = Parameters()
        if(param_file is not None):
            if(path.exists(param_file)):
                params.load(param_file)
                '''
                this part initializes the lattice parameters, atom positions in asymmetric 
                unit, occupation and the isotropic debye waller factor. the anisotropic DW 
                factors will be added in the future
                '''
                for p in self.phases:
                    l = list(self.phases[p].keys())[0]

                    mat = self.phases[p][l] 
                    lp       = np.array(mat.lparms)
                    rid      = list(_rqpDict[mat.latticeType][0])

                    lp       = lp[rid]
                    name     = _lpname[rid]

                    for n,l in zip(name,lp):
                        nn = p+'_'+n
                        '''
                        is l is small, it is one of the length units
                        else it is an angle
                        '''
                        if(l < 10.):
                            params.add(nn,value=l,lb=l-0.05,ub=l+0.05,vary=False)
                        else:
                            params.add(nn,value=l,lb=l-1.,ub=l+1.,vary=False)

                    atom_pos   = mat.atom_pos[:,0:3]
                    occ        = mat.atom_pos[:,3]
                    atom_type  = mat.atom_type

                    atom_label = _getnumber(atom_type)
                    self.atom_label = atom_label

                    for i in range(atom_type.shape[0]):

                        Z = atom_type[i]
                        elem = constants.ptableinverse[Z]
                        
                        nn = p+'_'+elem+str(atom_label[i])+'_x'
                        params.add(nn,value=atom_pos[i,0],lb=0.0,ub=1.0,vary=False)

                        nn = p+'_'+elem+str(atom_label[i])+'_y'
                        params.add(nn,value=atom_pos[i,1],lb=0.0,ub=1.0,vary=False)

                        nn = p+'_'+elem+str(atom_label[i])+'_z'
                        params.add(nn,value=atom_pos[i,2],lb=0.0,ub=1.0,vary=False)

                        nn = p+'_'+elem+str(atom_label[i])+'_occ'
                        params.add(nn,value=occ[i],lb=0.0,ub=1.0,vary=False)

                        if(mat.aniU):
                            U = mat.U
                            for j in range(6):
                                nn = p+'_'+elem+str(atom_label[i])+'_'+_nameU[j]
                                params.add(nn,value=U[i,j],lb=-1e-3,ub=np.inf,vary=False)
                        else:

                            nn = p+'_'+elem+str(atom_label[i])+'_dw'
                            params.add(nn,value=mat.U[i],lb=0.0,ub=np.inf,vary=False)

            else:
                raise FileError('parameter file doesn\'t exist.')
        else:
            '''
                first 6 are the lattice paramaters
                next three are cagliotti parameters
                next are the three gauss+lorentz mixing paramters
                final is the zero instrumental peak position error
            '''
            names   = ('a','b','c','alpha','beta','gamma',\
                      'U','V','W','eta1','eta2','eta3','tth_zero',\
                      'scale')
            values  = (5.415, 5.415, 5.415, 90., 90., 90., \
                        0.5, 0.5, 0.5, 1e-3, 1e-3, 1e-3, 0., \
                        1.0)

            lbs         = (-np.Inf,) * len(names)
            ubs         = (np.Inf,)  * len(names)
            varies  = (False,)   * len(names)

            params.add_many(names,values=values,varies=varies,lbs=lbs,ubs=ubs)

        self.params = params

        self._scale = self.params['scale'].value

        self._Ul = self.params['Ul'].value
        self._Vl = self.params['Vl'].value
        self._Wl = self.params['Wl'].value
        self._Pl = self.params['Pl'].value
        self._Xl = self.params['Xl'].value
        self._Yl = self.params['Yl'].value

        self._Ur = self.params['Ur'].value
        self._Vr = self.params['Vr'].value
        self._Wr = self.params['Wr'].value
        self._Pr = self.params['Pr'].value
        self._Xr = self.params['Xr'].value
        self._Yr = self.params['Yr'].value

        self._eta1 = self.params['eta1'].value
        self._eta2 = self.params['eta2'].value
        self._eta3 = self.params['eta3'].value

        self._zero_error = self.params['zero_error'].value

    '''
        no params are varied
    '''
    def params_vary_off(self):

        for p in self.params:
            self.params[p].vary = False

    '''
            all params are varied
    '''
    def params_vary_on(self):

        for p in self.params:
            self.params[p].vary = True

    '''
        turn all cagliotti parameters on
    '''
    def params_cagliotti_vary_on(self):
        self.params['Ul'].vary = True
        self.params['Vl'].vary = True
        self.params['Wl'].vary = True
        self.params['Pl'].vary = True

        self.params['Ur'].vary = True
        self.params['Vr'].vary = True
        self.params['Wr'].vary = True
        self.params['Pr'].vary = True

    '''
        turn all cagliotti parameters off
    '''
    def params_cagliotti_vary_off(self):
        self.params['Ul'].vary = False
        self.params['Vl'].vary = False
        self.params['Wl'].vary = False

        self.params['Ur'].vary = False
        self.params['Vr'].vary = False
        self.params['Wr'].vary = False
        self.params['Pr'].vary = False

    '''
        turn all lorentz half widths parameters on
    '''
    def params_lorentz_vary_on(self):
        self.params['Xl'].vary = True
        self.params['Yl'].vary = True

        self.params['Xr'].vary = True
        self.params['Yr'].vary = True

    '''
        turn all lorentz half widths parameters off
    '''
    def params_lorentz_vary_off(self):
        self.params['Xl'].vary = False
        self.params['Yl'].vary = False

        self.params['Xr'].vary = False
        self.params['Yr'].vary = False

    '''
        turn all mixing parameters on
    '''
    def params_eta_vary_on(self):
        self.params['eta1'].vary = True
        self.params['eta2'].vary = True
        self.params['eta3'].vary = True

    '''
        turn all mixing parameters off
    '''
    def params_eta_vary_off(self):
        self.params['eta1'].vary = False
        self.params['eta2'].vary = False
        self.params['eta3'].vary = False

    '''
        turn all lattice paramater on
    '''
    def params_lp_vary_all_on(self):

        for p in self.phases:

            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l] 
            rid      = list(_rqpDict[mat.latticeType][0])
            name     = _lpname[rid]
            for n in name:
                nn = p+'_'+n
                self.params[nn].vary = True

    '''
        turn all lattice paramater off
    '''
    def params_lp_vary_all_off(self):

        for p in self.phases:

            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l] 
            rid      = list(_rqpDict[mat.latticeType][0])
            name     = _lpname[rid]
            for n in name:
                nn = p+'_'+n
                self.params[nn].vary = False

    '''
        turn lattice paramater for a phase on
    '''
    def params_lp_vary_phase_on(self, phase_name):

        l = list(self.phases[phase_name].keys())[0]
        mat = self.phases[phase_name][l] 
        rid      = list(_rqpDict[mat.latticeType][0])
        name     = _lpname[rid]
        for n in name:
            nn = phase_name+'_'+n
            self.params[nn].vary = True

    '''
        turn lattice paramater for a phase off
    '''
    def params_lp_vary_phase_off(self, phase_name):

        l = list(self.phases[phase_name].keys())[0]
        mat = self.phases[phase_name][l] 
        rid      = list(_rqpDict[mat.latticeType][0])
        name     = _lpname[rid]
        for n in name:
            nn = phase_name+'_'+n
            self.params[nn].vary = False

    '''
        turn all the debye waller factors on
    '''
    def params_U_vary_all_on(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                if(mat.aniU):
                    U = mat.U
                    for j in range(6):
                        nn = p+'_'+elem+str(self.atom_label[i])+'_'+_nameU[j]
                        self.params[nn].vary = True
                else:

                    nn = p+'_'+elem+str(self.atom_label[i])+'_dw'
                    self.params[nn].vary = True

    '''
        turn all the debye waller factors on
    '''
    def params_U_vary_all_off(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                if(mat.aniU):
                    U = mat.U
                    for j in range(6):
                        nn = p+'_'+elem+str(self.atom_label[i])+'_'+_nameU[j]
                        self.params[nn].vary = False
                else:

                    nn = p+'_'+elem+str(self.atom_label[i])+'_dw'
                    self.params[nn].vary = False

    '''
        turn all the debye waller factors 
        for an atom label off
    '''
    def params_U_vary_label_off(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                if(mat.aniU):
                    U = mat.U
                    for j in range(6):
                        nn = p+'_'+label+'_'+_nameU[j]
                        self.params[nn].vary = False
                else:
                    nn = p+'_'+label+'_dw'
                    self.params[nn].vary = False
            else:
                raise ValueError('element not present any of the phases')

    '''
        turn all the debye waller factors 
        for an atom label on
    '''
    def params_U_vary_label_on(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                if(mat.aniU):
                    U = mat.U
                    for j in range(6):
                        nn = p+'_'+label+'_'+_nameU[j]
                        self.params[nn].vary = True
                else:
                    nn = p+'_'+label+'_dw'
                    self.params[nn].vary = True
            else:
                raise ValueError('element not present any of the phases')

    '''
        turn all the occupation factors on
    '''
    def params_occ_vary_all_on(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                nn = p+'_'+elem+str(self.atom_label[i])+'_occ'
                self.params[nn].vary = True

    '''
        turn all the occupation factors on
    '''
    def params_occ_vary_all_off(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                nn = p+'_'+elem+str(self.atom_label[i])+'_occ'
                self.params[nn].vary = False

    '''
        turn all the occupation factors 
        for an atom label off
    '''
    def params_occ_vary_label_off(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                nn = p+'_'+label+'_occ'
                self.params[nn].vary = False
            else:
                raise ValueError('element not present any of the phases')

    '''
        turn all the occupation factors 
        for an atom label on
    '''
    def params_occ_vary_label_on(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                nn = p+'_'+label+'_occ'
                self.params[nn].vary = True
            else:
                raise ValueError('element not present any of the phases')

    '''
        turn all the atom positions factors on
    '''
    def params_xyz_vary_all_on(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                nn = p+'_'+elem+str(self.atom_label[i])+'_x'
                self.params[nn].vary = True
                nn = p+'_'+elem+str(self.atom_label[i])+'_y'
                self.params[nn].vary = True
                nn = p+'_'+elem+str(self.atom_label[i])+'_z'
                self.params[nn].vary = True

    '''
        turn all the atom positions factors on
    '''
    def params_xyz_vary_all_off(self):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem = constants.ptableinverse[Z]

                nn = p+'_'+elem+str(self.atom_label[i])+'_x'
                self.params[nn].vary = False
                nn = p+'_'+elem+str(self.atom_label[i])+'_y'
                self.params[nn].vary = False
                nn = p+'_'+elem+str(self.atom_label[i])+'_z'
                self.params[nn].vary = False

    '''
        turn all the atom positions
        for an atom label off
    '''
    def params_xyz_vary_label_off(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                nn = p+'_'+label+'_x'
                self.params[nn].vary = False
                nn = p+'_'+label+'_y'
                self.params[nn].vary = False
                nn = p+'_'+label+'_z'
                self.params[nn].vary = False
            else:
                raise ValueError('element not present any of the phases')

    '''
        turn all the atom positions
        for an atom label on
    '''
    def params_xyz_vary_label_on(self, label):

        for p in self.phases:
            l = list(self.phases[p].keys())[0]
            mat = self.phases[p][l]
            atom_type  = mat.atom_type

            elem_all = []
            for i in range(atom_type.shape[0]):
                Z = atom_type[i]
                elem_all.append(constants.ptableinverse[Z])

            elem = label[:-1]
            if(elem in elem_all):
                nn = p+'_'+label+'_x'
                self.params[nn].vary = True
                nn = p+'_'+label+'_y'
                self.params[nn].vary = True
                nn = p+'_'+label+'_z'
                self.params[nn].vary = True
            else:
                raise ValueError('element not present any of the phases')

    def initialize_expt_spectrum(self, expt_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    load the experimental spectum of 2theta-intensity
        '''
        # self.spectrum_expt = Spectrum.from_file()
        if(expt_file is not None):
            if(path.exists(expt_file)):
                self.spectrum_expt = Spectrum.from_file(expt_file,skip_rows=0)
                self.tth_max = np.amax(self.spectrum_expt._x)
                self.tth_min = np.amin(self.spectrum_expt._x)

                ''' also initialize statistical weights for the error calculation'''
                self.weights = 1.0 / np.sqrt(self.spectrum_expt.y)
                self.initialize_bkg()
            else:
                raise FileError('input spectrum file doesn\'t exist.')

    def initialize_bkg(self):

        '''
            the cubic spline seems to be the ideal route in terms
            of determining the background intensity. this involves 
            selecting a small (~5) number of points from the spectrum,
            usually called the anchor points. a cubic spline interpolation
            is performed on this subset to estimate the overall background.
            scipy provides some useful routines for this
        '''
        self.selectpoints()
        x = self.points[:,0]
        y = self.points[:,1]
        self.splinefit(x, y)

    def selectpoints(self):

        fig = plt.figure()
        ax = fig.add_subplot(111)
        ax.set_title('Select 7 points for background estimation')

        line = ax.plot(self.tth_list, self.spectrum_expt._y, '-b', picker=7)  # 6 points tolerance
        plt.show()

        self.points = np.asarray(plt.ginput(7,timeout=-1, show_clicks=True))
        plt.close()

    # cubic spline fit of background using custom points chosen from plot
    def splinefit(self, x, y):
        cs = CubicSpline(x,y)
        bkg = cs(self.tth_list)
        self.background = Spectrum(x=self.tth_list, y=bkg)

    def initialize_phases(self, phase_file):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       06/08/2020 SS 1.0 original
        >> @DETAILS:    load the phases for the LeBail fits
        '''
        p = Phases_Rietveld(wavelength=self.wavelength)
        if(phase_file is not None):
            if(path.exists(phase_file)):
                p.load(phase_file)
            else:
                raise FileError('phase file doesn\'t exist.')
        self.phases = p

        self.calctth()
        self.calcsf()

    def calctth(self):
        self.tth = {}
        for p in self.phases:
            self.tth[p] = {}
            for k,l in self.phases.wavelength.items():
                t,_ = self.phases[p][k].getTTh(l[0].value)
                limit = np.logical_and(t >= self.tth_min,\
                                       t <= self.tth_max)
                self.tth[p][k] = t[limit]

    def calcsf(self):
        self.sf = {}
        for p in self.phases:
            self.sf[p] = {}
            for k,l in self.phases.wavelength.items():
                w_int = l[1]
                t,tmask = self.phases[p][k].getTTh(l[0].value)
                limit = np.logical_and(t >= self.tth_min,\
                                       t <= self.tth_max)
                hkl = self.phases[p][k].hkls[tmask][limit]
                multiplicity = self.phases[p][k].multiplicity[tmask][limit]
                sf = []
                for m,g in zip(multiplicity,hkl):
                    sf.append(w_int * m * self.phases[p][k].CalcXRSF(g))
                self.sf[p][k] = np.array(sf)

    def CagliottiH(self, tth, branch):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
                        07/20/2020 SS 1.1 branch keyword for asymmetric profiles
        >> @DETAILS:    calculates the cagiotti parameter for the peak width

        '''
        th          = np.radians(0.5*tth)
        tanth       = np.tan(th)
        cth         = np.cos(th)
        if(branch == 'l'):
            Hsq         = self.Ul * tanth**2 + self.Vl * tanth + self.Wl + self.Pl / cth**2
        elif(branch == 'r'):
            Hsq         = self.Ur * tanth**2 + self.Vr * tanth + self.Wr + self.Pr / cth**2

        if(Hsq < 0.):
            Hsq = 1.0e-12
        self.Hcag   = np.sqrt(Hsq)

    def LorentzH(self, tth, branch):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       07/20/2020 SS 1.0 original
        >> @DETAILS:    calculates the size and strain broadening for Lorentzian peak
        '''
        th = np.radians(0.5*tth)
        tanth       = np.tan(th)
        cth         = np.cos(th)
        if(branch == 'l'):
            self.gamma = self.Xl/cth + self.Yl * tanth
        elif(branch == 'r'):
            self.gamma = self.Xr/cth + self.Yr * tanth

        if(self.gamma < 0.):
            self.gamma = 1e-6

    def MixingFact(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    calculates the mixing factor eta
        '''
        self.eta = self.eta1 + self.eta2 * tth + self.eta3 * (tth)**2

        if(self.eta > 1.0):
            self.eta = 1.0

        elif(self.eta < 0.0):
            self.eta = 0.0

    def Gaussian(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the gaussian peak profile
        '''
        mask = self.tth_list < tth
        cg = 4.*np.log(2.)

        self.CagliottiH(tth, 'l')
        H  = self.Hcag
        Il = (np.sqrt(cg/np.pi)/H) * np.exp( -cg * ((self.tth_list[mask] - tth)/H)**2 )

        self.CagliottiH(tth, 'r')
        H  = self.Hcag
        Ir = (np.sqrt(cg/np.pi)/H) * np.exp( -cg * ((self.tth_list[~mask] - tth)/H)**2 )

        if(Il.size == 0):
            a = 0.
            b = 1.
        elif(Ir.size == 0):
            a = 1.
            b = 0.
        else:
            Ilm = np.amax(Il)
            Irm = np.amax(Ir)
            if(Ilm == 0):
                a = 1.
                b = 0.
            elif(Irm == 0):
                a = 0.
                b = 1.
            else:
                b = 2./(1. + Irm/Ilm)
                a = b * Irm / Ilm

        self.GaussianI = np.hstack((a*Il, b*Ir))

    def Lorentzian(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the lorentzian peak profile
        '''
        mask = self.tth_list < tth
        cl = 4.

        self.LorentzH(tth, 'l')
        H = self.gamma
        Il = (2./np.pi/H) / ( 1. + cl*((self.tth_list[mask] - tth)/H)**2)

        self.LorentzH(tth, 'r')
        H = self.gamma
        Ir = (2./np.pi/H) / ( 1. + cl*((self.tth_list[~mask] - tth)/H)**2)

        if(Il.size == 0):
            a = 0.
            b = 1.
        elif(Ir.size == 0):
            a = 1.
            b = 0.
        else:
            Ilm = np.amax(Il)
            Irm = np.amax(Ir)
            if(Ilm == 0):
                a = 1.
                b = 0.
            elif(Irm == 0):
                a = 0.
                b = 1.
            else:
                b = 2./(1. + Irm/Ilm)
                a = b * Irm / Ilm

        self.LorentzI = np.hstack((a*Il, b*Ir))

    def PseudoVoight(self, tth):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/20/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the pseudo-voight function as weighted 
                        average of gaussian and lorentzian
        '''

        self.Gaussian(tth)
        self.Lorentzian(tth)
        self.MixingFact(tth)

        self.PV = self.eta * self.GaussianI + \
                  (1.0 - self.eta) * self.LorentzI

    def PolarizationFactor(self):

        tth = np.radians(self.tth_list)
        self.LP = (1 + np.cos(tth)**2)/ \
        np.cos(0.5*tth)/np.sin(0.5*tth)**2

    def computespectrum(self):

        I = np.zeros(self.tth_list.shape)
        for p in self.tth:
            for l in self.tth[p]:

                tth = self.tth[p][l]
                sf  = self.sf[p][l]
                pf = self.phases[p][l].pf / self.phases[p][l].vol**2

                for t,fsq in zip(tth,sf):
                    self.PseudoVoight(t+self.zero_error)
                    I += self.scale * pf * self.PV * fsq * self.LP

        self.spectrum_sim = Spectrum(self.tth_list, I) + self.background

    def calcRwp(self, params):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    this routine computes the weighted error between calculated and
                        experimental spectra. goodness of fit is also calculated. the 
                        weights are the inverse squareroot of the experimental intensities
        '''

        '''
        the err variable is the difference between simulated and experimental spectra
        '''
        for p in params:
            if(hasattr(self, p)):
                setattr(self, p, params[p].value)

        self.updated_lp = False
        self.updated_atominfo = False
        for p in self.phases:
            for l in self.phases[p]:

                mat = self.phases[p][l]

                '''
                PART 1: update the lattice parameters
                '''
                lp = []

                pre = p + '_'
                if(pre+'a' in params):
                    if(params[pre+'a'].vary):
                        lp.append(params[pre+'a'].value)
                if(pre+'b' in params):
                    if(params[pre+'b'].vary):
                        lp.append(params[pre+'b'].value)
                if(pre+'c' in params):
                    if(params[pre+'c'].vary):
                        lp.append(params[pre+'c'].value)
                if(pre+'alpha' in params):
                    if(params[pre+'alpha'].vary):
                        lp.append(params[pre+'alpha'].value)
                if(pre+'beta' in params):
                    if(params[pre+'beta'].vary):
                        lp.append(params[pre+'beta'].value)
                if(pre+'gamma' in params):
                    if(params[pre+'gamma'].vary):
                        lp.append(params[pre+'gamma'].value)

                if(not lp):
                    pass
                else:
                    lp = self.phases[p][l].Required_lp(lp)
                    self.phases[p][l].lparms = np.array(lp)
                    self.updated_lp = True
                '''
                PART 2: update the atom info
                '''

                atom_type = mat.atom_type

                for i in range(atom_type.shape[0]):

                    Z = atom_type[i]
                    elem = constants.ptableinverse[Z]
                    nx = p+'_'+elem+str(self.atom_label[i])+'_x'
                    ny = p+'_'+elem+str(self.atom_label[i])+'_y'
                    nz = p+'_'+elem+str(self.atom_label[i])+'_z'
                    oc = p+'_'+elem+str(self.atom_label[i])+'_occ'

                    if(mat.aniU):
                        Un = []
                        for j in range(6):
                            Un.append(p+'_'+elem+str(self.atom_label[i])+'_'+_nameU[j])
                    else:
                        dw = p+'_'+elem+str(self.atom_label[i])+'_dw'

                    if(nx in params):
                        x = params[nx].value
                        self.updated_atominfo = True
                    else:
                        x = self.params[nx].value

                    if(ny in params):
                        y = params[ny].value
                        self.updated_atominfo = True
                    else:
                        y = self.params[ny].value

                    if(nz in params):
                        z = params[nz].value
                        self.updated_atominfo = True
                    else:
                        z = self.params[nz].value

                    if(oc in params):
                        oc = params[oc].value
                        self.updated_atominfo = True
                    else:
                        oc = self.params[oc].value

                    if(mat.aniU):
                        U = []
                        for j in range(6):
                            if(Un[j] in params):
                                self.updated_atominfo = True
                                U.append(params[Un[j]].value)
                            else:
                                U.append(self.params[Un[j]].value)
                        U = np.array(U)
                        mat.U[i,:] = U
                    else:
                        if(dw in params):
                            dw = params[dw].value
                            self.updated_atominfo = True
                        else:
                            dw = self.params[dw].value
                        mat.U[i] = dw

                    mat.atom_pos[i,:] = np.array([x,y,z,oc])

                if(mat.aniU):
                    mat.calcBetaij()
                if(self.updated_lp):
                    mat._calcrmt()

        if(self.updated_lp):
            self.calctth()
        if(self.updated_lp or self.updated_atominfo):
            self.calcsf()

        self.computespectrum()

        self.err = (self.spectrum_sim - self.spectrum_expt)

        errvec = np.sqrt(self.weights * self.err._y**2)

        ''' weighted sum of square '''
        wss = np.trapz(self.weights * self.err._y**2, self.err._x)

        den = np.trapz(self.weights * self.spectrum_sim._y**2, self.spectrum_sim._x)

        ''' standard Rwp i.e. weighted residual '''
        Rwp = np.sqrt(wss/den)

        ''' number of observations to fit i.e. number of data points '''
        N = self.spectrum_sim._y.shape[0]

        ''' number of independent parameters in fitting '''
        P = len(params)
        Rexp = np.sqrt((N-P)/den)

        # Rwp and goodness of fit parameters
        self.Rwp = Rwp
        self.gofF = (Rwp / Rexp)**2

        return errvec

    def initialize_lmfit_parameters(self):

        params = lmfit.Parameters()

        for p in self.params:
            par = self.params[p]
            if(par.vary):
                params.add(p, value=par.value, min=par.lb, max = par.ub)

        return params

    def update_parameters(self):

        for p in self.res.params:
            par = self.res.params[p]
            self.params[p].value = par.value

    def Refine(self):
        '''
        >> @AUTHOR:     Saransh Singh, Lawrence Livermore National Lab, saransh1@llnl.gov
        >> @DATE:       05/19/2020 SS 1.0 original
        >> @DETAILS:    this routine performs the least squares refinement for all variables
                        which are allowed to be varied.
        '''

        params = self.initialize_lmfit_parameters()

        fdict = {'ftol':1e-4, 'xtol':1e-4, 'gtol':1e-4, \
                 'verbose':0, 'max_nfev':8}

        fitter = lmfit.Minimizer(self.calcRwp, params)

        self.res = fitter.least_squares(**fdict)

        self.update_parameters()

        self.niter += 1
        self.Rwplist  = np.append(self.Rwplist, self.Rwp)
        self.gofFlist = np.append(self.gofFlist, self.gofF)

        print('Finished iteration. Rwp: {:.3f} % goodness of fit: {:.3f}'.format(self.Rwp*100., self.gofF))

    @property
    def Ul(self):
        return self._Ul

    @Ul.setter
    def Ul(self, Uinp):
        self._Ul = Uinp
        # self.computespectrum()
        return

    @property
    def Vl(self):
        return self._Vl

    @Vl.setter
    def Vl(self, Vinp):
        self._Vl = Vinp
        # self.computespectrum()
        return

    @property
    def Wl(self):
        return self._Wl

    @Wl.setter
    def Wl(self, Winp):
        self._Wl = Winp
        # self.computespectrum()
        return

    @property
    def Pl(self):
        return self._Pl

    @Pl.setter
    def Pl(self, Pinp):
        self._Pl = Pinp
        return

    @property
    def Xl(self):
        return self._Xl

    @Xl.setter
    def Xl(self, Xinp):
        self._Xl = Xinp
        return

    @property
    def Yl(self):
        return self._Yl

    @Yl.setter
    def Yl(self, Yinp):
        self._Yl = Yinp
        return

    @property
    def Ur(self):
        return self._Ur

    @Ur.setter
    def Ur(self, Uinp):
        self._Ur = Uinp
        return

    @property
    def Vr(self):
        return self._Vr

    @Vr.setter
    def Vr(self, Vinp):
        self._Vr = Vinp
        return

    @property
    def Wr(self):
        return self._Wr

    @Wr.setter
    def Wr(self, Winp):
        self._Wr = Winp
        return

    @property
    def Pr(self):
        return self._Pr

    @Pr.setter
    def Pr(self, Pinp):
        self._Pr = Pinp
        return

    @property
    def Xr(self):
        return self._Xr

    @Xr.setter
    def Xr(self, Xinp):
        self._Xr = Xinp
        return

    @property
    def Yr(self):
        return self._Yr

    @Yr.setter
    def Yr(self, Yinp):
        self._Yr = Yinp
        return

    @property
    def gamma(self):
        return self._gamma
    
    @gamma.setter
    def gamma(self, val):
        self._gamma = val

    @property
    def Hcag(self):
        return self._Hcag

    @Hcag.setter
    def Hcag(self, val):
        self._Hcag = val

    @property
    def eta1(self):
        return self._eta1

    @eta1.setter
    def eta1(self, val):
        self._eta1 = val
        return

    @property
    def eta2(self):
        return self._eta2

    @eta2.setter
    def eta2(self, val):
        self._eta2 = val
        return

    @property
    def eta3(self):
        return self._eta3

    @eta3.setter
    def eta3(self, val):
        self._eta3 = val
        return

    @property
    def tth_list(self):
        return self.spectrum_expt._x

    @property
    def zero_error(self):
        return self._zero_error
    
    @zero_error.setter
    def zero_error(self, value):
        self._zero_error = value
        return

    @property
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, value):
        self._scale = value
        return

_rqpDict = {
    'triclinic': (tuple(range(6)), lambda p: p),  # all 6
    'monoclinic': ((0,1,2,4), lambda p: (p[0], p[1], p[2], 90, p[3], 90)), # note beta
    'orthorhombic': ((0,1,2),   lambda p: (p[0], p[1], p[2], 90, 90,   90)),
    'tetragonal': ((0,2),     lambda p: (p[0], p[0], p[1], 90, 90,   90)),
    'trigonal': ((0,2),     lambda p: (p[0], p[0], p[1], 90, 90,  120)),
    'hexagonal': ((0,2),     lambda p: (p[0], p[0], p[1], 90, 90,  120)),
    'cubic': ((0,),      lambda p: (p[0], p[0], p[0], 90, 90,   90)),
    }

_lpname = np.array(['a','b','c','alpha','beta','gamma'])
_nameU  = np.array(['U11','U22','U33','U12','U13','U23'])

def _getnumber(arr):

    res = np.ones(arr.shape)
    for i in range(arr.shape[0]):
        res[i] = np.sum(arr[0:i+1] == arr[i])
    res = res.astype(np.int32)

    return res