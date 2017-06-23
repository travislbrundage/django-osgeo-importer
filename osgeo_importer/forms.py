import logging
import os
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

    # TODO: If all works, reformat and resubmit
    def process_zip(self, zipfile, outputdir, cleaned_files=[], prefix=''):
        check_nesteds = []
        all_names = zipfile.namelist()
        for zipname in zipfile.namelist():
            base_prefix = prefix
            filename = zipname.split(os.extsep, 1)
            # is a directory
            if len(filename) == 1:
                # Walk through directories, flatten any subdirectories, and process any subzips
                for dirpath, dirnames, filenames in os.walk(outputdir):
                    for f in filenames:
                        # TODO: Check this is grabbing zip file correctly
                        # Theoretically we can copy the part below?
                        if is_zipfile(os.path.join(dirpath, f)):
                            with ZipFile(zipfile.open(os.path.join(dirpath, f))) as zf:
                                cleaned_files = self.process_zip(zf, outputdir, cleaned_files)
                        # We don't have to worry about subdir case here because of how os.walk works
                        # TODO: Check all subfiles and subdirectories are parsed correctly this way
                        else:
                            # This prevents repeating the directory prefix and the top level directory
                            # TODO: Check the top level compressed folder's name is not used
                            if os.path.basename(dirpath) != os.path.basename(outputdir):
                                prefix = '{}{}_'.format(prefix, os.path.basename(dirpath))
                            # TODO: Fix what we're doing here - need to use prefix
                            # This should be the same as normal behaviour
                            if f in VALID_EXTENSIONS:
                                with zipfile.open(zipname) as zf:
                                    mkdir_p(os.path.join(outputdir, os.path.dirname(zipname)))
                                    with open(os.path.join(outputdir, zipname), 'w') as outfile:
                                        shutil.copyfileobj(zf, outfile)
                                        cleaned_files.append(outfile)
                            # Instead, do this to every subdirectory file at the beginning of the loop?
                            # Calculate the prefix, then keep everything the same -except- add prefix
                            '''
                            try:
                                os.rename(os.path.join(dirpath, f), os.path.join(outputdir, prefix + f))
                            except OSError:
                                # TODO: Check this logs error correctly
                                logger.error('Could not move {}'.format(os.path.join(dirpath, f)))
                            '''
            # is a zipfile
            elif filename[1] == 'zip':
                # zip file recurse
                # how to create new zipfile with this sub zip file correctly?
                # filename is just the name, we probably need full path to it?
                # is it just os.path?
                # os.path.abspath?
                # TODO: Check this is grabbing zip file correctly
                # Perhaps we need to extract it?
                # why does iz_zipfile return false if there's a zip in the name?
                #if is_zipfile(zipname):
                    # Why does open fail?
                    # it's because of the spaces in name?
                nested_zip = zipfile.extract(zipname)
                check_nesteds.append(nested_zip)
                prefix = '{}{}_'.format(base_prefix, filename[0])
                with ZipFile(nested_zip) as zf:
                    cleaned_files = self.process_zip(zf, outputdir, cleaned_files, prefix)
                #else:
                #    check_nesteds.remove('asjfdlkajlfjakfd')
            # standard behaviour
            # This part works!
            elif filename[1] in VALID_EXTENSIONS:
                with zipfile.open(zipname) as zf:
                    mkdir_p(os.path.join(outputdir, os.path.dirname(zipname)))
                    with open(os.path.join(outputdir, base_prefix + zipname), 'w') as outfile:
                        shutil.copyfileobj(zf, outfile)
                        cleaned_files.append(outfile)

        return cleaned_files

    def clean(self):
        local_extensions = VALID_EXTENSIONS
        cleaned_data = super(UploadFileForm, self).clean()
        outputdir = tempfile.mkdtemp()
        files = self.files.getlist('file')
        # Files that need to be processed
        process_files = []

        # Create list of all potentially valid files, exploding first level zip files
        zip_files = []
        reg_files = []
        for f in files:
            if is_zipfile(f):
                zip_files.append(f)
            else:
                reg_files.append(f)

        for rf in reg_files:
            errors = valid_file(rf)
            if errors != []:
                self.add_error('file', ', '.join(errors))
                continue
            process_files.append(rf.name)

        # Make sure shapefiles have all their parts
        if not validate_shapefiles_have_all_parts(process_files):
            self.add_error('file', 'Shapefiles must include .shp,.dbf,.shx,.prj')

        # Unpack all zip files and create list of cleaned file objects, excluding any not in
        #    VALID_EXTENSIONS
        cleaned_files = []
        for rf in reg_files:
            if rf.name in process_files:
                with open(os.path.join(outputdir, rf.name), 'w') as outfile:
                    for chunk in rf.chunks():
                        outfile.write(chunk)
                cleaned_files.append(outfile)
            '''
            elif is_zipfile(f):
                with ZipFile(f) as zip:
                    for zipfile in zip.namelist():
                        if zipfile in process_files:
                            with zip.open(zipfile) as zf:
                                mkdir_p(os.path.join(outputdir, os.path.dirname(zipfile)))
                                with open(os.path.join(outputdir, zipfile), 'w') as outfile:
                                    shutil.copyfileobj(zf, outfile)
                                    cleaned_files.append(outfile)
            '''
        # Regular files opens: os.path.join(outputdir, f.name)
        # which is path/to/outputdir/<name of file>
        # We want to do essentially the same thing with the zip file
        # outputdir is where we extract it to
        # path/to/outputdir/<name of extracted file>
        # So make a function which takes
        # zip file
        # directory to extract to
        # process_zip(zipfile, outputdir)
        # for file in name list
        # if the file is a directory
        # get the dirname of this name - see what this gives
        # os.walk through this directory?
        # Maybe just copy the os.walk part of the process_zip.py
        # Only instead of what we do in is_zipfile, recurse
        # if the file is a zip, recurse
        # if it's not a zip or directory
        # Dow hat we have below - extract it to the outputdir

        for zf in zip_files:
            with ZipFile(zf) as zip:
                # TODO: see if this works, uncomment and remove below
                cleaned_files = self.process_zip(zip, outputdir, cleaned_files)
                #for zipname in zip.namelist():
                #    with zip.open(zipname) as zipfile:
                #        mkdir_p(os.path.join(outputdir, os.path.dirname(zipname)))
                #        with open(os.path.join(outputdir, zipname), 'w') as outfile:
                #            shutil.copyfileobj(zipfile, outfile)
                #            cleaned_files.append(outfile)
                #for zipname in zip.namelist():
                #    mkdir_p(os.path.join(outputdir, os.path.dirname(zipname)))
                #    zip.extract(zipname, os.path.join(outputdir, os.path.dirname(zipname)))
        # generate error to check what's in cleaned_files
        # cleaned_files.remove('afdsfsaf')
        # In order to do this, we may remove the part above where regular files
        # are added to cleaned_files
        # This removes our need for extracted_files
        # TODO: Ensure this works with zip, regular files, and nested
        # This doesn't work because it's not getting it as a file
        #for dirpath, dirnames, filenames in os.walk(outputdir):
        #    for f in filenames:
        #        if f not in process_files:
        #            with open(os.path.join(outputdir, f), 'w') as cf:
        #                cleaned_files.append(cf)

        '''
        extracted_files = []
        for zf in zip_files:
            # Extract them
            # Validate them
            with ZipFile(zf) as zip:
                for zipname in zip.namelist():
                    filename = zipname.split(os.extsep, 1)
                    # is a directory
                    if len(filename) == 1:
                        # need to figure out what to do here
                        with zip.open(zipname) as zipfile:
                            zip_dir = dir(zipfile)
                            zip_dir_type = type(zipfile)
                    else:
                        zipext = filename[1]
                        zipext = zipext.lstrip('.').lower()
                        if zipext in VALID_EXTENSIONS:
                            if zipext == 'zip':
                                # recursion?
                                with zip.open(zipname) as zipfile:
                                    zip_zip = dir(zipfile)
                                    zip_zip_type = type(zipfile)
                            else:
                                with zip.open(zipname) as zipfile:
                                    mkdir_p(os.path.join(outputdir, os.path.dirname(zipname)))
                                    with open(os.path.join(outputdir, zipname), 'w') as outfile:
                                        shutil.copyfileobj(zipfile, outfile)
                                        extracted_files.append(outfile)
        '''
        '''
        if is_zipfile(f):
            with ZipFile(f) as zip:
                for zipname in zip.namelist():
                    _, zipext = zipname.split(os.extsep, 1)
                    zipext = zipext.lstrip('.').lower()
                    if zipext in VALID_EXTENSIONS:
                        process_files.append(zipname)
        '''

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
        # random failure should happen
        # cleaned_data.remove('asfdjasfd')
        return cleaned_data
