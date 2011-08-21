#!/usr/bin/env python
"""

bugbuster.py -- Runs multiple Static Analysis tools over C files,
currently supports Splint and TenDRA.

Copyright (c) 2011, Daniel Molina Wegener <dmw@coder.cl>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the Daniel Molina Wegener nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""

import re
import sys

from subprocess import Popen, PIPE, STDOUT
from optparse import OptionParser
from ConfigParser import ConfigParser


class LintRunner(object):
    """
    Base Lint output capture and processing class.
    """

    alias = False

    output_format = ("%(level)s %(error_type)s%(error_number)s:"
                     "%(description)s at %(filename)s line %(line_number)s.\n")

    output_template = dict.fromkeys(('level',
                                     'error_type',
                                     'error_number',
                                     'description',
                                     'filename',
                                     'line_number'), '')

    output_matcher = None

    process_stderr = True

    sane_default_ignore_codes = set([])

    command = None

    line = None

    run_flags = []

    def __init__(self, ignore_codes=(), use_sane_defaults=True):
        global CONFIG
        global LINT_DEFAULT
        global options
        self.ignore_codes = set(ignore_codes)
        if use_sane_defaults:
            self.ignore_codes ^= self.sane_default_ignore_codes
        if not CONFIG:
            return
        if CONFIG.has_section('global') \
           and CONFIG.has_option('global', 'includes'):
            includes = CONFIG.get('global', 'includes')
            if includes:
                includes = map(lambda x: "-I" + x, includes.split(":"))
                self.run_flags.extend(includes)
        if CONFIG.has_section('global') \
           and CONFIG.has_option('global', 'suppress'):
            options.suppress = CONFIG.getboolean('global', 'suppress')
        if CONFIG.has_section('global') \
           and CONFIG.has_option('global', 'defaults'):
            defaults = CONFIG.get('global', 'defaults')
            LINT_DEFAULT = map(lambda x: x.strip("\n\r "), defaults.split(":"))
        if not self.alias or not CONFIG.has_section(self.alias):
            return
        if CONFIG.has_option(self.alias, 'flags'):
            flags = CONFIG.get(self.alias, 'flags')
            flags = map(lambda x: x.strip("\n\r "), flags.split(":"))
            self.run_flags.extend(flags)
        if CONFIG.has_option(self.alias, 'ignore'):
            ignore = CONFIG.get(self.alias, 'ignore')
            ignore = map(lambda x: x.strip("\n\r "), ignore.split(":"))
            options.ignore = ignore
        if CONFIG.has_option(self.alias, 'noincludes'):
            ignore = CONFIG.getboolean(self.alias, 'noincludes')
            nflags = []
            if ignore:
                nflags = filter(lambda x: not x.startswith("-I"),
                                self.run_flags)
            self.run_flags = nflags

    def fixup_data(self, line, data):
        """ Fixes data for missing elements """
        self.line = line
        return data

    def process_output(self, line):
        """ Process output chcker output """
        matcher = self.output_matcher.match(line)
        if matcher:
            return matcher.groupdict()
        return False

    def run(self, filename):
        """ Run the checker over the file """
        global options
        args_ = [self.command]
        args_.extend(self.run_flags)
        args_.append(filename)

        process = Popen(args_, stdout=PIPE, stderr=STDOUT)

        for line in process.stdout:
            match = self.process_output(line)
            if not match:
                continue
            tokens = dict(self.output_template)
            fixed = self.fixup_data(line, match)
            if not fixed:
                continue
            tokens.update(fixed)
            tokens['description'] = tokens['description'].\
                                    strip("\n\r ")
            pass_out = True
            for subs in options.ignore:
                if subs in tokens['description'] \
                   or subs in line:
                    pass_out = False
            if not pass_out:
                continue
            if not options.suppress:
                print self.output_format % tokens
            if filename == tokens['filename']:
                print self.output_format % tokens


class LintSplint(LintRunner):
    """
    Run splint static checker
    """

    alias = 'splint'

    run_flags = ['+matchanyintegral',
                 '+tryrecover',
                 '-sysdirerrors',
                 '-syntax',
                 '-indentspaces', '0',
                 '-linelen', '8192',
                 '-localindentspaces', '0',
                 '-bugslimit', '1000']

    command = 'splint'

    output_matcher = re.compile(r'^(?P<filename>[^:]+):'
                                r'(?P<line_number>[^:]+):'
                                r'(?P<column_number>[^:]+): '
                                r'(?P<description>.+)$')

    process_stderr = False

    def fixup_data(self, line, data):
        if "*** Internal Bug" in line:
            return False
        data['level'] = 'WARNING'
        data['error_type'] = 'SPL'
        data['error_number'] = 'E01'
        return data


class LintCppCheck(LintRunner):
    """
    Run splint static checker
    """

    alias = 'cppcheck'

    run_flags = ['--enable=style',
                 '--enable=unusedFunction',
                 '--enable=information']

    command = 'cppcheck'

    output_matcher = re.compile(r'^\[(?P<filename>[^:]+):'
                                r'(?P<line_number>[^:]+)\]: '
                                r'\((?P<level>[^\)]+)\) '
                                r'(?P<description>[^\r\n]+)$')

    process_stderr = True

    def fixup_data(self, line, data):
        data['level'] = data['level'].upper()
        data['error_type'] = 'CCH'
        data['error_number'] = 'E01'
        return data


class LintTendra(LintRunner):
    """
    Run TenDRA static checker
    """

    alias = 'tendra'

    double_pass = False

    run_flags = ['-Xs',
                 '-Yxpg4',
                 '-Yposix2',
                 '-I./',
                 '-I./include',
                 '-I/usr/include/python2.7',
                 '-I/usr/include/libxml2']

    command = 'tchk'

    output_matcher_error = re.compile(r'^[ ]+(?P<description>[^\r\n$]+)')

    output_matcher = re.compile(
        r'^\"(?P<filename>[^,]+)\",[ ]*line[ ]*'
        r'(?P<line_number>[^:]+):[ ]*Error:[\n\r]',
        re.I | re.M)

    def fixup_data(self, line, data):
        data['level'] = 'WARNING'
        data['error_type'] = 'TCH'
        data['error_number'] = 'E01'
        return data

    def process_output(self, line):
        """ Process output chcker output """
        matcher = self.output_matcher.match(line)
        if matcher:
            grpd = matcher.groupdict()
            self.double_pass = grpd
            return False
        else:
            matcher = self.output_matcher_error.match(line)
            if matcher:
                grpd = matcher.groupdict()
                if not self.double_pass:
                    self.double_pass = grpd
                else:
                    self.double_pass['description'] = grpd['description']
                return self.double_pass

options = False

CONFIG = False

LINT_DEFAULT = ['cppcheck', 'tendra', 'splint']

LINT_MAP = {'tendra': LintTendra,
            'splint': LintSplint,
            'cppcheck': LintCppCheck}


def parse_options():
    """ Parse the program options """
    opt_parser = OptionParser()
    lint_hlp = "Add a lint program to use (defaults: %s)" \
               % (LINT_DEFAULT)
    opt_parser.add_option("-l",
                          "--lint",
                          default=LINT_DEFAULT,
                          action="append",
                          dest="lint",
                          metavar="BUG_LINT",
                          help=lint_hlp)
    opt_parser.add_option("-e",
                          "--env",
                          default=[],
                          action="append",
                          dest="env",
                          metavar="BUG_ENV",
                          help="Adds environment variable")
    opt_parser.add_option("-c",
                          "--config",
                          default="./.bugbuster.ini",
                          dest="config",
                          metavar="BUG_CONFIG",
                          help="Uses the configuration file")
    opt_parser.add_option("-f",
                          "--files",
                          default=[],
                          action="append",
                          dest="files",
                          metavar="FILES",
                          help="File to process (twice to add more files)")
    opt_parser.add_option("-s",
                          "--suppress",
                          default=False,
                          action="store_true",
                          dest="suppress",
                          metavar="SUPPRESS",
                          help="Suppress messages in other files")
    opt_parser.add_option("-i",
                          "--ignore",
                          default=[],
                          action="append",
                          dest="ignore",
                          metavar="IGNORE",
                          help="Ignore lines with substring, twice to add")
    options, arguments = opt_parser.parse_args()
    return options


def main():
    """ Main function/program """
    global options
    options = parse_options()
    global CONFIG
    if len(options.files) <= 0:
        print("No files specified")
        sys.exit(0)
    if options.config:
        CONFIG = ConfigParser()
        CONFIG.read(options.config)
    for lnt in options.lint:
        if lnt in LINT_MAP:
            cls = (LINT_MAP[lnt])()
            for fln in options.files:
                print("-" * 64)
                print("Running '%s' over '%s'" \
                      % (lnt, fln))
                cls.run(fln)


if __name__ == "__main__":
    main()
