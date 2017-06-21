import logging
import os
import sys
import shutil
import tempfile
from zipfile import is_zipfile, ZipFile

from django import forms

from osgeo_importer.importers import VALID_EXTENSIONS
from osgeo_importer.utils import mkdir_p
from osgeo_importer.validators import valid_file

from .models import UploadFile
from .validators import validate_inspector_can_read, validate_shapefiles_have_all_parts


logger = logging.getLogger(__name__)


class UploadFileForm(forms.Form):
    file = forms.FileField(widget=forms.ClearableFileInput(attrs={'multiple': True}))

    class Meta:
        model = UploadFile
        fields = ['file']

    def process_zip(self, zipfile, extractdir=None):
        '''
        Extracts and flattens a zip file and returns the list of files within it.
        '''
        if type(zipfile) is not ZipFile:
            if not is_zipfile(zipfile):
                return []
            else:
                zipfile = ZipFile(zipfile)

        if extractdir is None:
            extractdir = tempfile.mkdtemp()
        zipfile.extractall(extractdir)
        basezip = os.path.basename(zipfile.filename)
        # Zipfile has already been extracted, remove it if it is still present
        if basezip in os.listdir(extractdir):
            os.remove('{}/{}'.format(extractdir, basezip))

        # Walk through directories, flatten any subdirectories, and process any subzips
        for dirpath, dirnames, filenames in os.walk(extractdir):
            for f in filenames:
                if is_zipfile(os.path.join(dirpath, f)):
                    filenames.extend(self.process_zip(os.path.join(dirpath, f), dirpath))
                    filenames.remove(f)
                else:
                    # This prevents repeating the directory prefix and the top level directory
                    if os.path.basename(dirpath) != os.path.basename(extractdir):
                        prefix = '{}_'.format(os.path.basename(dirpath))
                    else:
                        prefix = ''
                    try:
                        os.rename(os.path.join(dirpath, f), os.path.join(extractdir, prefix + f))
                    except OSError:
                        print ("Could not move %s " % os.path.join(dirpath, f))

        # return flat list of all files extracted
        return [f for f in os.listdir(extractdir) if os.path.isfile(os.path.join(extractdir, f))]

    def clean(self):
        cleaned_data = super(UploadFileForm, self).clean()
        outputdir = tempfile.mkdtemp()
        files = self.files.getlist('file')
        # Files that need to be processed
        process_files = []

        # Create list of all potentially valid files, exploding first level zip files
        for f in files:
            errors = valid_file(f)
            if errors != []:
                self.add_error('file', ', '.join(errors))
                continue

            if is_zipfile(f):
                with ZipFile(f) as zip:
                    zip_files = self.process_zip(zip, outputdir)
                    for zf in zip_files:
                        _, zipext = zf.split(os.extsep, 1)
                        zipext = zipext.lstrip('.').lower()
                        if zipext in VALID_EXTENSIONS:
                            process_files.append(zf)
            else:
                process_files.append(f.name)

        # Make sure shapefiles have all their parts
        if not validate_shapefiles_have_all_parts(process_files):
            self.add_error('file', 'Shapefiles must include .shp,.dbf,.shx,.prj')

        # Unpack all zip files and create list of cleaned file objects, excluding any not in
        #    VALID_EXTENSIONS
        cleaned_files = []
        for f in files:
            if f.name in process_files:
                with open(os.path.join(outputdir, f.name), 'w') as outfile:
                    for chunk in f.chunks():
                        outfile.write(chunk)
                cleaned_files.append(outfile)

        # Have a separate check for all files in zip files?

        # After moving files in place make sure they can be opened by inspector
        inspected_files = []
        for cleaned_file in cleaned_files:
            cleaned_file_path = os.path.join(outputdir, cleaned_file.name)
            if not validate_inspector_can_read(cleaned_file_path):
                self.add_error(
                    'file',
                    'Inspector could not read file {} or file is empty'.format(cleaned_file_path)
                )
                continue
            inspected_files.append(cleaned_file)

        cleaned_data['file'] = inspected_files
        cleaned_data.remove('nonefile')
        return cleaned_data
