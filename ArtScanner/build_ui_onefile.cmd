pyinstaller -w -F --clean --add-data "weights-improvement-55-1.00.hdf5;." --add-data "Tools/ReliquaryLevelExcelConfigData.json;./Tools" --add-data "Tools/ReliquaryAffixExcelConfigData.json;./Tools" --hidden-import=h5py --hidden-import=h5py.defs --hidden-import=h5py.utils --hidden-import=h5py.h5ac --hidden-import=h5py._proxy --uac-admin -n ArtScannerUI UImain.py