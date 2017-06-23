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

    def process_zip(self, zipfile, outputdir, cleaned_files=[], prefix=''):
        check_nesteds = []
        all_names = zipfile.namelist()
        base_prefix = prefix
        for zipname in zipfile.namelist():
            filename = zipname.split(os.extsep, 1)
            # is a directory
            # This is now the only one not working correctly
            # It's not correctly prepending the current directory
            if len(filename) == 1:
                # New attempt starts here
                cleaned_files = flatten_directory(cleaned_files)
                for item in os.listdir(os.path(outputdir)):
                    prefix = '{}{}_'.format(base_prefix, os.path.dirname(item))
                    if os.path.isfile(item):
                        if is_zipfile(item):
                            with ZipFile(zipfile.open(os.path(item))) as zf:
                                cleaned_files = self.process_zip(zf, outputdir, cleaned_files, prefix)
                        else:
                            with zipfile.open(zipname) as zf:
                                mkdir_p(os.path.join(outputdir, os.path.dirname(zipname)))
                                # Seems like we just don't want this base_prefix? Why would we? was base_prefix + zipname
                                # We may also need to actually remove the last prefix
                                # Which would be to take everything before the final _
                                # Then use that as the prefix here instead of base_prefix
                                final_index = base_prefix[-1:].rfind('_')
                                if final_index > -1:
                                    final_prefix = base_prefix[:final_index]
                                else:
                                    final_prefix = base_prefix
                                with open(os.path.join(outputdir, final_prefix + zipname), 'w') as outfile:
                                    shutil.copyfileobj(zf, outfile)
                                    cleaned_files.append(outfile)
                    else:
                        # recurse with new destination being this dir
            # is a zipfile
            # TODO: This is appending too much to the prefix
            elif filename[1] == 'zip':
                # zip file recurse
                nested_zip = zipfile.extract(zipname)
                check_nesteds.append(nested_zip)
                prefix = '{}{}_'.format(base_prefix, filename[0])
                with ZipFile(nested_zip) as zf:
                    cleaned_files = self.process_zip(zf, outputdir, cleaned_files, prefix)
                    # check what base_prefix is here
            # standard behaviour
            # This part works!
            elif filename[1] in VALID_EXTENSIONS:
                with zipfile.open(zipname) as zf:
                    mkdir_p(os.path.join(outputdir, os.path.dirname(zipname)))
                    # Seems like we just don't want this base_prefix? Why would we? was base_prefix + zipname
                    # We may also need to actually remove the last prefix
                    # Which would be to take everything before the final _
                    # Then use that as the prefix here instead of base_prefix
                    final_index = base_prefix[-1:].rfind('_')
                    if final_index > -1:
                        final_prefix = base_prefix[:final_index]
                    else:
                        final_prefix = base_prefix
                    with open(os.path.join(outputdir, final_prefix + zipname), 'w') as outfile:
                        shutil.copyfileobj(zf, outfile)
                        cleaned_files.append(outfile)

        return cleaned_files


    def flatten_directory(cleaned_files):
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

        for zf in zip_files:
            with ZipFile(zf) as zip:
                cleaned_files = self.process_zip(zip, outputdir, cleaned_files)
                # old method
                #for zipname in zip.namelist():
                #    with zip.open(zipname) as zipfile:
                #        mkdir_p(os.path.join(outputdir, os.path.dirname(zipname)))
                #        with open(os.path.join(outputdir, zipname), 'w') as outfile:
                #            shutil.copyfileobj(zipfile, outfile)
                #            cleaned_files.append(outfile)
                #for zipname in zip.namelist():
                #    mkdir_p(os.path.join(outputdir, os.path.dirname(zipname)))
                #    zip.extract(zipname, os.path.join(outputdir, os.path.dirname(zipname)))

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
        return cleaned_data
