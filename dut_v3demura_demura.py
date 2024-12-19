import os
import shutil
import time
import sys
import logging
import cv2
import numpy as np
from logging.handlers import TimedRotatingFileHandler
from ctypes import CDLL, c_char_p, c_bool, create_string_buffer, byref, c_float, c_ubyte
from threading import Lock

errcode_description = {
    '0000': 'Success',
    '0005': 'Powerboard Hardware error',
    '0006': 'Powerboard Hardware version mismatch',
    '0007': 'No vendor id',
    '0008': 'MP3314 Config Error',
    '0009': 'Panel is not 0x9c',
    '8001': 'IOVCC Voltage over upper-limit 10P Mode',
    '8002': 'IOVCC Voltage below lower-limit 10P Mode',
    '8003': 'VSP Voltage over upper-limit 10P Mode',
    '8004': 'VSP Voltage below lower-limit 10P Mode',
    '8005': 'VSN Voltage over upper-limit 10P Mode',
    '8006': 'VSN Voltage below lower-limit 10P Mode',
    '8007': 'VLED Voltage over upper-limit 10P Mode',
    '8008': 'VLED Voltage below lower-limit 10P Mode',
    '8009': 'IOVCC Current over upper-limit 10P Mode',
    '8010': 'IOVCC Current below lower-limit 10P Mode',
    '8011': 'VSP Current over upper-limit 10P Mode',
    '8012': 'VSP Current below lower-limit 10P Mode',
    '8013': 'VSN Current over upper-limit 10P Mode',
    '8014': 'VSN Current below lower-limit 10P Mode',
    '8015': 'LED1 Current over upper-limit 10P Mode',
    '8016': 'LED1 Current below lower-limit 10P Mode',
    '8017': 'LED2 Current over upper-limit 10P Mode',
    '8018': 'LED2 Current below lower-limit 10P Mode',
    '8024': 'LED1 Current below lower-limit 100P Mode',
    '8025': 'LED2 Current below lower-limit 100P Mode',
    '8027': 'LED1 Current over upper-limit 100P Mode',
    '8028': 'LED2 Current over upper-limit 100P Mode',
    '9999': 'Communication exception',
}


class DUTError(Exception):
    def __init__(self, value, errcode=-1):
        Exception.__init__(self)
        self.value = value
        self.err_code = errcode

    def __str__(self):
        return repr(f'{self.value} + errcode: {self.err_code}, '
                    f'errmsg: {errcode_description.get(self.err_code, None)}')


class MyzyDDS(object):
    retain_count = 1
    lock = Lock()

    def __init__(self, verbose=False):
        self.is_screen_poweron = False
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.INFO)
        self._spliter = ','
        self._nvm_data_len = 28
        self._dll = None
        self._host = None
        self._current_host = None
        self._emulator_mode = False

        fn_path = 'DemuraDLL.dll'

        try:
            dll_path = fn_path
            if not os.path.exists(fn_path):
                dll_path = os.path.join(os.path.dirname(os.path.abspath(
                    sys.modules[MyzyDDS.__module__].__file__)), fn_path)
            if verbose:
                format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                log_handel = TimedRotatingFileHandler('myzyDDS.log', when='D')
                log_handel.setFormatter(logging.Formatter(format))
                self._logger.addHandler(log_handel)
                self._logger.setLevel(logging.DEBUG)

            MyzyDDS.lock.acquire()
            if MyzyDDS.retain_count > 1:
                dll_cpy = f'_{MyzyDDS.retain_count}'.join(os.path.splitext(dll_path))
                if os.path.exists(dll_cpy):
                    shutil.rmtree(dll_cpy, ignore_errors=True)
                shutil.copyfile(dll_path, dll_cpy)
                dll_path = dll_cpy
            self._dll = CDLL(dll_path)
            MyzyDDS.retain_count += 1

            MyzyDDS.lock.release()
        except Exception as e:
            raise

    def enable_emulator(self, emulator):
        self._emulator_mode = emulator

    def open_device(self, host='192.168.21.132'):
        """
        * @brief initialize.
        * @Param [in] host: 192.168.21.address (address do not use 1 or 255)
        * @return Return to the status
        """
        self.is_screen_poweron = False
        self._host = host

        self._dll.EnableEmulator(self._emulator_mode)
        res = self._dll.OpenDevice(c_char_p(str(host).encode('utf-8')))
        if res != 0:
            errcode = self.get_error_code()
            raise DUTError(f'Unable to connect DUT. Received: {res}', errcode=errcode)
        self._current_host = host

        self._logger.debug('DUT Initialised ip %s. ' % host)
        return True

    def power_on(self, ntype=0):
        """
        * @brief screen on.
        * @Param [in] ntype: 0 = DSCMode_10P , 1 = DSCMode_100P
        * @return Return to the status
        """
        if not self.is_screen_poweron:
            recv = self._dll.PowerON(ntype)  # type  0 = DSCMode_10P , 1 = DSCMode_100P
            if recv != 0:
                errcode = self.get_error_code()
                raise DUTError("Exit power_on because power_on failed.", errcode=errcode)
            self.is_screen_poweron = True
            self._logger.debug(f"screen on success.")
            return True

    def power_off(self):
        """
        * @brief screen off.
        * @return Return to the status
        """
        recv = self._dll.PowerOFF()
        if recv != 0:
            errcode = self.get_error_code()
            raise DUTError("Exit power_off because power_off failed.", errcode=errcode)
        self._logger.debug(f"screen off success.")
        self.is_screen_poweron = False
        return True

    def close_device(self):
        """
        * @brief close device.
        """
        self._dll.CloseDevice()
        self._logger.debug("Closing DUT.")
        self.is_screen_poweron = False

    def _show_EMMC_image(self, image):
        """
        * @brief show image.
        * @Param [in] image: index or name
        * @return Return to the status
        """
        if not isinstance(image, (int, str)):
            raise NotImplementedError('Argument is error. Arg type should be int or str')
        res = None
        if isinstance(image, int):
            res = self._dll.ShowEMMCImageIndex(image)
        elif isinstance(image, str):
            res = self._dll.ShowEMMCImageName(c_char_p(image.encode('utf-8')))
        if res != 0:
            errcode = self.get_error_code()
            raise DUTError(f'Fail to show image {image}.', errcode=errcode)
        self._logger.debug(f"show image {image} success................")
        return True

    def show_emmc_image(self, image):
        """
        * @brief show image.
        * @Param [in] image: index or name
        * @return Return to the status
        """
        return self._show_EMMC_image(image)

    def read_version(self):
        """
        * @brief get the version of FW.
        * @return Return the FW version
        """
        res_ver = create_string_buffer(128)
        rec = self._dll.ReadVersion(byref(res_ver))
        if rec != 0:
            errcode = self.get_error_code()
            raise DUTError(f'Unable to get FW version. Received: {rec}', errcode=errcode)
        res_ver = res_ver.value.decode('utf-8')
        self._logger.debug(f"Read FW version: {res_ver}")
        return res_ver

    def read_dll_version(self):
        """
        * @brief get the version of DLL.
        * @return Return the DLL version
        """
        res_ver = create_string_buffer(128)
        rec = self._dll.ReadDLLVersion(byref(res_ver))
        if rec != 0:
            errcode = self.get_error_code()
            raise DUTError(f'Unable to get DLL version. Received: {rec}', errcode=errcode)
        res_ver = res_ver.value.decode('utf-8')
        res_ver = res_ver.split(':')[1].strip()
        self._logger.debug(f"Read DLL version: {res_ver}")
        return res_ver

    def reset(self):
        """
        * @brief reset DUT
        * @return Return to the status
        """
        self.power_off()
        self._dll.CloseDevice()

        self.open_device(self._current_host)
        return True

    def write_image_to_emmc(self, filenames: list, isToRGB, iRotationType, nTailor, tailorWidth, tailorHeight,
                            timeout=6000):
        """
        @ Param [in] fileNames; the path array for the burned pictures.
        * @ Param [in] fileNum; the number of burned pictures.
        * @ Param [in] isToRGB; turn the picture to RGB, the default three channels is BGR, true refers to RGB, and false means not turning.
        * @ Param [in] iRotationType; rotate the picture,1: rotate 180 degrees, 2: X image, 3: Y image,4: X image、Y image.
        * @ Param [in] nTailor; supplement the position of the picture data, 0: no; 1: to the right; 2: middle; 3: left.
        * @ Param [in] tailorWidth; complete the picture width, if nTailor=0, the change parameter is invalid.
        * @ Param [in] tailorHeight; complete the picture height, if nTailor=0, the change parameter is invalid.
        * @ Param [in] timeout; timeout time in milliseconds.
        * @return Return to the status
        """

        if not isinstance(filenames, list):
            raise NotImplementedError(f'Arguments are not supported. filenames should be list')
        file_nums = len(filenames)
        c_files = (c_char_p * file_nums)()
        for file in range(file_nums):
            c_files[file] = filenames[file].encode('utf-8')

        res = self._dll.WriteImageToEMMC(c_files, file_nums, c_bool(isToRGB), iRotationType, nTailor, tailorWidth,
                                         tailorHeight, timeout)
        if res != 0:
            self._logger.debug(f"write image Failed, return: {res}")
            errcode = self.get_error_code()
            raise DUTError(f'write image to EMMC Err. ', errcode=errcode)

        self._logger.debug("write image success................")
        return True

    def get_emmc_image_name(self, buffer=384):
        """
        * @brief Gets a list of EMMC images in PG
        * @Param [out] namelist; Output name list.
        * @return Return to the status
        """
        res = None
        namelist_buffer = create_string_buffer(buffer)
        res = self._dll.GetEMMCImageName(byref(namelist_buffer))
        if res != 0:
            errcode = self.get_error_code()
            raise DUTError(f'get emmc image name err', errcode=errcode)
        namelist = namelist_buffer.value.decode('utf-8')
        namelist = namelist.split(',')

        self._logger.debug(f"get emmc image name success................{namelist}")
        return namelist

    def set_device_ip_address(self, addr):
        """
        * After changing the ip address, you must reconnect with the new ip address
        * Device must be open with the OpenDevice function before using this function
        * After using this function, the CloseDevice function must close the device and wait for the device to restart,
        then reconnect the DUT.
        * @ Param [in] address; do not use 1 or 255, IP number: 192.168.21.address
        * @return Returns to the status
        * @par instance:
        * @code
        *   OpenDevice(6000,"192.168.21.132");
        *   SetDeviceIpAddress(134);
        *   CloseDevice();
        * @endcode
        """
        rec = self._dll.SetDeviceIpAddress(addr)
        if rec != 0:
            errcode = self.get_error_code()
            raise DUTError(f'Fail to set IP addr {addr}', errcode=errcode)
        self._current_host = f'192.168.21.{addr}'
        self._logger.debug(f"set ip to {addr} success......")
        return True

    def set_rgb(self, r, g, b):
        """
        * @brief Set the color of the display
        * Device must be open with the OpenDevice & PowerOn function before using this function
        * @Param [in] Red value
        * @Param [in] Green value
        * @Param [in] Blue value
        * @return Return to the status
        """
        res = self._dll.SetRGB(r, g, b)
        if res != 0:
            errcode = self.get_error_code()
            raise DUTError('set rgb failed.', errcode=errcode)

        self._logger.debug(f"set rgb success......")
        return True

    def _decode_msg(self, msg_code):
        res_val = create_string_buffer(2*1024)
        rec = self._dll.Decoding(msg_code, byref(res_val))
        if rec != 0:
            errcode = self.get_error_code()
            raise DUTError(f'Unable to _decode_msg', errcode=errcode)
        return res_val.value.decode('utf-8')

    def get_error_code(self):
        """
        * @brief Return the last exception code for the device
        * @return Return to the Exception code , find the abnormal problem by looking up the table
        """
        res_ver = create_string_buffer(128)
        self._dll.GetErrorCode(byref(res_ver))
        return res_ver.value

    def demura_mode(self, mode):
        """
        * @brief demura_mode
        * @Param [in] mode= 0,1,2.
        * @return Return to the status
        """
        recv = self._dll.DemuraMode(mode)  # type  0, 1, 2
        if recv != 0:
            errcode = self.get_error_code()
            raise DUTError("demura_mode  failed.", errcode=errcode)
        self._logger.debug(f"demura_mode success. {mode}")
        return True

    def load_demura_file(self, filename, crc=0):
        crc_ = (c_ubyte * 2)()
        crc_.value = crc.to_bytes(2, 'big')
        recv = self._dll.LoadDemuraFile(create_string_buffer(filename.encode('utf-8')), crc_)
        if recv != 0:
            errcode = self.get_error_code()
            raise DUTError("load_demura_file  failed.", errcode=errcode)
        self._logger.debug(f"load_demura_file success.")
        return True

    def before_demura_poweron(self):
        """
        * @brief before_demura_poweron
        * @Param
        * @return Return to the status
        """
        recv = self._dll.BeforeDemuraPowerOn()
        if recv != 0:
            errcode = self.get_error_code()
            raise DUTError("BeforeDemuraPowerOn  failed.", errcode=errcode)
        self._logger.debug(f"BeforeDemuraPowerOn success.")
        return True

    def demura_write(self):
        """
        * @brief demura_write
        * @Param
        * @return Return to the status
        """
        recv = self._dll.DemuraWrite()
        if recv != 0:
            errcode = self.get_error_code()
            raise DUTError("DemuraWrite  failed.", errcode=errcode)
        self._logger.debug(f"DemuraWrite success.")
        return True

    def demura_protection(self, mode):
        """
        * @brief demura_protection
        * @Param mode = 0
        * @return Return to the status
        """
        recv = self._dll.DemuraProtection(mode)
        if recv != 0:
            errcode = self.get_error_code()
            raise DUTError("DemuraProtection  failed.", errcode=errcode)
        self._logger.debug(f"DemuraProtection success.")
        return True

    def after_demura_poweron(self):
        """
        * @brief AfterDemuraPowerOn
        * @Param
        * @return Return to the status
        """
        recv = self._dll.AfterDemuraPowerOn()
        if recv != 0:
            errcode = self.get_error_code()
            raise DUTError("AfterDemuraPowerOn  failed.", errcode=errcode)
        self._logger.debug(f"AfterDemuraPowerOn success.")
        return True

    def demura_OTP(self):
        """
        * @brief demura_OTP
        * @Param
        * @return Return to the status
        """
        recv = self._dll.DemuraOTP()
        if recv != 0:
            errcode = self.get_error_code()
            raise DUTError("DemuraOTP  failed.", errcode=errcode)
        self._logger.debug(f"DemuraOTP success.")
        return True

    def demura_read(self, filename):
        recv = self._dll.DemuraRead(create_string_buffer(filename.encode('utf-8')))
        if recv != 0:
            errcode = self.get_error_code()
            raise DUTError("DemuraRead  failed.", errcode=errcode)
        self._logger.debug(f"DemuraRead success.")
        return True
    # </editor-fold>


if __name__ == "__main__":
    sys.path.append(r'..\..')
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    the_unit = MyzyDDS(verbose=True)
    try:
        # set to False if PG is on hand.
        run_dll_in_emulator_mode = False
        the_unit.enable_emulator(run_dll_in_emulator_mode)

        the_unit.open_device('192.168.21.132')
        the_unit.reset()
        the_unit.read_version()
        the_unit.read_dll_version()
        # the_unit.power_on()
        #
        # name_list = the_unit.get_emmc_image_name()
        # the_unit.power_on(0)
        #
        # for image_name in name_list:
        #     the_unit.show_emmc_image(image_name)
        # for image_index in range(len(name_list)):
        #     the_unit.show_emmc_image(image_index)
        #
        # the_unit.set_rgb(255, 255, 0)
        # the_unit.power_off()

        # mura data should write/read follow this sequence.
        the_unit.load_demura_file('./lut_x_pattern_2160x2312_mode2_flash.bin', 0x4bde)
        the_unit.demura_mode(2)
        the_unit.before_demura_poweron()
        the_unit.demura_protection(1)
        the_unit.demura_write()  # Write the demura data.
        the_unit.demura_protection(0)
        the_unit.after_demura_poweron()
        # the_unit.demura_OTP()

        the_unit.set_rgb(127,127,127)
        time.sleep(5)
        the_unit.power_off()

        #after opt run
        the_unit.power_on(0) # if OTP is enabled, line 455-467 will not be needed. 12/18/2024
        the_unit.set_rgb(127,127,127)
        time.sleep(5)
        the_unit.power_off()

        # w, h = 2160, 2312
        # raw_data = np.tile((255, 0, 0), (h, w, 1))
        # cv2.imwrite('b255.bmp', raw_data)
        #
        # raw_data = np.tile((0, 255, 0), (h, w, 1))
        # cv2.imwrite('g255.bmp', raw_data)
        #
        # the_unit.write_image_to_emmc(['b255.bmp', 'g255.bmp'], False, 1, 0, w, h, 2000 * 2)
        # name_list = the_unit.get_emmc_image_name()
        # for image_name in name_list:
        #     the_unit.show_emmc_image(image_name)
        # for image_index in range(len(name_list)):
        #     the_unit.show_emmc_image(image_index)

    except DUTError as e:
        print(f'Fail to run all seq. {e.value} : {e.err_code}')
    except Exception as e:
        print(f'Fail: {str(e)}')
