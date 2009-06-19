"""
Write Python egg file, either directly or via setuptools.
Supports what's needed for saving and loading components/simulations.
"""

import copy
import os.path
import subprocess
import sys
import time
import zipfile

__all__ = ('egg_filename', 'write', 'write_via_setuptools')


def egg_filename(name, version):
    """ Returns name for egg file as generated by setuptools. """
    return '%s-%s-py%s.egg' % (name, version, sys.version[:3])


def write(name, doc, version, loader, src_files, distributions,
          dst_dir, logger, compress=True):
    """
    Write egg in manner of setuptools, with some differences:

    - Write directly to zip file, avoiding some intermediate copies.
    - Don't compile any Python modules.

    Returns egg filename.
    """
    egg_name = egg_filename(name, version)
    egg_path = os.path.join(dst_dir, egg_name)

    # Determine approximate (uncompressed) size.  Used to set allowZip64 flag
    # and potentially also useful for a progress display.
    sources = []
    files = []
    bytes = 0

    # Collect src_files.
    for path in src_files:
        path = os.path.join(name, path)
        files.append(path)
        bytes += os.path.getsize(path)

    # Collect Python modules.
    # TODO: use 2.6 followlinks.
    for dirpath, dirnames, filenames in os.walk('.'):
        dirs = copy.copy(dirnames)
        for path in dirs:
            if not os.path.exists(os.path.join(dirpath, path, '__init__.py')):
                dirnames.remove(path)
        for path in filenames:
            if path.endswith('.py'):
                path = os.path.join(dirpath, path)
                files.append(path)
                bytes += os.path.getsize(path)
                sources.append(path+'\n')

    if os.path.islink(name):
        for dirpath, dirnames, filenames in os.walk(name):
            dirs = copy.copy(dirnames)
            for path in dirs:
                if not os.path.exists(os.path.join(dirpath, path, '__init__.py')):
                    dirnames.remove(path)
            for path in filenames:
                if path.endswith('.py'):
                    path = os.path.join(dirpath, path)
                    files.append(path)
                    bytes += os.path.getsize(path)
                    sources.append(path+'\n')

    # Eggsecutable support.
    sh_prefix = """\
#!/bin/sh
if [ `basename $0` = "%(egg_name)s" ]
then exec python%(py_version)s -c "import sys, os; sys.path.insert(0, os.path.abspath('$0')); from openmdao.main.component import eggsecutable; sys.exit(eggsecutable())" "$@"
else
  echo $0 is not the correct name for this egg file.
  echo Please rename it back to %(egg_name)s and try again.
  exec false
fi
""" % {'egg_name':egg_name, 'py_version':sys.version[:3]}
    bytes += len(sh_prefix)

    # Package info -> EGG-INFO/PKG-INFO
    pkg_info = """\
Metadata-Version: 1.0
Name: %(name)s
Version: %(version)s
Summary: %(doc)s
Home-page: UNKNOWN
Author: UNKNOWN
Author-email: UNKNOWN
License: UNKNOWN
Description: UNKNOWN
Platform: UNKNOWN
""" % {'name':name.replace('_', '-'), 'version':version, 'doc':doc.strip()}
    sources.append(name+'.egg-info/PKG-INFO\n')
    bytes += len(pkg_info)

    # Dependency links -> EGG-INFO/dependency_links.txt
    dependency_links = '\n'
    sources.append(name+'.egg-info/dependency_links.txt\n')
    bytes += len(dependency_links)

    # Entry points -> EGG-INFO/entry_points.txt
    entry_points = """\
[openmdao.components]
%(name)s = %(name)s.%(loader)s:load

[openmdao.top]
top = %(loader)s:load

[setuptools.installation]
eggsecutable = openmdao.main.component:eggsecutable

""" % {'name':name, 'loader':loader}
    sources.append(name+'.egg-info/entry_points.txt\n')
    bytes += len(dependency_links)

    # Unsafe -> EGG-INFO/not-zip-safe
    not_zip_safe = '\n'
    sources.append(name+'.egg-info/not-zip-safe\n')
    bytes += len(not_zip_safe)

    # Requirements -> EGG-INFO/requires.txt
    requirements = ''
    for dist in sorted(distributions, key=lambda dist: dist.project_name):
        requirements += '%s == %s\n' % (dist.project_name, dist.version)
    sources.append(name+'.egg-info/requires.txt\n')
    bytes += len(requirements)

    # Top-level names -> EGG-INFO/top_level.txt
    top_level = '%s\n' % name
    sources.append(name+'.egg-info/top_level.txt\n')
    bytes += len(top_level)

    # Manifest -> EGG-INFO/SOURCES.txt
    sources.append(name+'.egg-info/SOURCES.txt\n')
    sources = ''.join(sorted(sources))
    bytes += len(sources)

    # Start with eggsecutable prefix.
    logger.debug('Creating %s', egg_path)
    egg = open(egg_path, 'w')
    egg.write(sh_prefix)
    egg.close()

    # Open zipfile.
    zip64 = bytes > zipfile.ZIP64_LIMIT
    compression = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    egg = zipfile.ZipFile(egg_path, 'a', compression, zip64)

    # Write egg info.
    _write_info(egg, 'PKG-INFO', pkg_info, logger)
    _write_info(egg, 'dependency_links.txt', dependency_links, logger)
    _write_info(egg, 'entry_points.txt', entry_points, logger)
    _write_info(egg, 'not-zip-safe', not_zip_safe, logger)
    _write_info(egg, 'requires.txt', requirements, logger)
    _write_info(egg, 'top_level.txt', top_level, logger)
    _write_info(egg, 'SOURCES.txt', sources, logger)

    # Write collected files.
    for path in sorted(files):
        _write_file(egg, path, logger)

    egg.close()
    if os.path.getsize(egg_path) > zipfile.ZIP64_LIMIT:
        logger.warning('Egg zipfile requires Zip64 support to unzip.')
    return egg_name

def _write_info(egg, name, info, logger):
    """ Write info string to egg. """
    path = os.path.join('EGG-INFO', name)
    logger.debug("    adding '%s'", path)
    egg.writestr(path, info)

def _write_file(egg, path, logger):
    """ Write file to egg. """
    logger.debug("    adding '%s'", path)
    egg.write(path)


def write_via_setuptools(name, doc, version, loader, src_files, distributions,
                         dst_dir, logger):
    """ Write an egg via setuptools. Returns egg filename. """ 
    _write_setup_py(name, doc, version, loader, src_files, distributions)

    # Use environment since 'python' might not recognize '-u'.
    env = os.environ
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.Popen(['python', 'setup.py', 'bdist_egg',
                             '-d', dst_dir], env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    output = []
    while proc.returncode is None:
        line = proc.stdout.readline()
        if line:
            line = line.rstrip()
            logger.debug('    '+line)
            output.append(line)
        time.sleep(0.1)
        proc.poll()
    line = proc.stdout.readline()
    while line:
        line = line.rstrip()
        logger.debug('    '+line)
        output.append(line)
        line = proc.stdout.readline()

    if proc.returncode != 0:
        for line in output:
            logger.error('    '+line)
        logger.error('save_to_egg failed due to setup.py error %d:',
                     proc.returncode)
        raise RuntimeError('setup.py failed, check log for info.')

    return egg_filename(name, version)


def _write_setup_py(name, doc, version, loader, src_files, distributions):
    """ Write setup.py file for installation later. """
    out = open('setup.py', 'w')
    
    out.write('import setuptools\n')

    out.write('\npackage_files = [\n')
    for filename in sorted(src_files):
        path = os.path.join(name, filename)
        if not os.path.exists(path):
            raise ValueError("Can't save, '%s' does not exist" % path)
        out.write("    '%s',\n" % filename)
    out.write(']\n')
    
    out.write('\nrequirements = [\n')
    for dist in distributions:
        out.write("    '%s == %s',\n" % (dist.project_name, dist.version))
    out.write(']\n')
    
    out.write("""
entry_points = {
    'openmdao.top' : [
        'top = %(loader)s:load',
    ],
    'openmdao.components' : [
        '%(name)s = %(name)s.%(loader)s:load',
    ],
    'setuptools.installation' : [
        'eggsecutable = openmdao.main.component:eggsecutable',
    ],
}

setuptools.setup(
    name='%(name)s',
    description='''%(doc)s''',
    version='%(version)s',
    packages=setuptools.find_packages(),
    package_data={'%(name)s' : package_files},
    zip_safe=False,
    install_requires=requirements,
    entry_points=entry_points,
)
""" % {'name':name, 'loader':loader, 'doc':doc.strip(), 'version':version})

    out.close()

