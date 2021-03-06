# -*- coding: utf-8 -*-
"""
    pyrseas.dbobject.textsearch
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~

    This defines eight classes: TSConfiguration, TSDictionary,
    TSParser and TSTemplate derived from DbSchemaObject, and
    TSConfigurationDict, TSDictionaryDict, TSParserDict and
    TSTemplateDict derived from DbObjectDict.
"""
from pyrseas.dbobject import DbObjectDict, DbSchemaObject
from pyrseas.dbobject import commentable, ownable, split_schema_obj


class TSConfiguration(DbSchemaObject):
    """A text search configuration definition"""

    keylist = ['schema', 'name']
    single_extern_file = True
    catalog = 'pg_ts_config'

    @property
    def objtype(self):
        return "TEXT SEARCH CONFIGURATION"

    def to_map(self, db, no_owner):
        """Convert a text search configuration to a YAML-suitable format

        :return: dictionary
        """
        dct = self._base_map(db, no_owner)
        if '.' in self.parser:
            (sch, pars) = self.parser.split('.')
            if sch == self.schema:
                dct['parser'] = pars
        return dct

    @commentable
    @ownable
    def create(self):
        """Return SQL statements to CREATE the configuration

        :return: SQL statements
        """
        clauses = []
        clauses.append("PARSER = %s" % self.parser)
        return ["CREATE TEXT SEARCH CONFIGURATION %s (\n    %s)" % (
                self.qualname(), ',\n    '.join(clauses))]

    def get_implied_deps(self, db):
        deps = super(TSConfiguration, self).get_implied_deps(db)
        deps.add(db.tsparsers[split_schema_obj(self.parser, self.schema)])
        return deps


class TSConfigurationDict(DbObjectDict):
    "The collection of text search configurations in a database"

    cls = TSConfiguration
    query = \
        """SELECT c.oid, nc.nspname AS schema, cfgname AS name,
                  rolname AS owner, np.nspname || '.' || prsname AS parser,
                  obj_description(c.oid, 'pg_ts_config') AS description
           FROM pg_ts_config c
                JOIN pg_roles r ON (r.oid = cfgowner)
                JOIN pg_ts_parser p ON (cfgparser = p.oid)
                JOIN pg_namespace nc ON (cfgnamespace = nc.oid)
                JOIN pg_namespace np ON (prsnamespace = np.oid)
           WHERE (nc.nspname != 'pg_catalog'
                  AND nc.nspname != 'information_schema')
           ORDER BY nc.nspname, cfgname"""

    def from_map(self, schema, inconfigs):
        """Initialize the dictionary of configs by examining the input map

        :param schema: schema owning the configurations
        :param inconfigs: input YAML map defining the configurations
        """
        for key in inconfigs:
            if not key.startswith('text search configuration '):
                raise KeyError("Unrecognized object type: %s" % key)
            tsc = key[26:]
            self[(schema.name, tsc)] = config = TSConfiguration(
                schema=schema.name, name=tsc)
            inconfig = inconfigs[key]
            if inconfig:
                for attr, val in list(inconfig.items()):
                    setattr(config, attr, val)
                if 'oldname' in inconfig:
                    config.oldname = inconfig['oldname']
                    del inconfig['oldname']
                if 'description' in inconfig:
                    config.description = inconfig['description']


class TSDictionary(DbSchemaObject):
    """A text search dictionary definition"""

    keylist = ['schema', 'name']
    single_extern_file = True
    catalog = 'pg_ts_dict'

    @property
    def objtype(self):
        return "TEXT SEARCH DICTIONARY"

    @commentable
    @ownable
    def create(self):
        """Return SQL statements to CREATE the dictionary

        :return: SQL statements
        """
        clauses = []
        clauses.append("TEMPLATE = %s" % self.template)
        if hasattr(self, 'options'):
            clauses.append(self.options)
        return ["CREATE TEXT SEARCH DICTIONARY %s (\n    %s)" % (
                self.qualname(), ',\n    '.join(clauses))]


class TSDictionaryDict(DbObjectDict):
    "The collection of text search dictionaries in a database"

    cls = TSDictionary
    query = \
        """SELECT d.oid, nspname AS schema, dictname AS name, rolname AS owner,
                  tmplname AS template, dictinitoption AS options,
                  obj_description(d.oid, 'pg_ts_dict') AS description
           FROM pg_ts_dict d JOIN pg_ts_template t ON (dicttemplate = t.oid)
                JOIN pg_roles r ON (r.oid = dictowner)
                JOIN pg_namespace n ON (dictnamespace = n.oid)
           WHERE (nspname != 'pg_catalog' AND nspname != 'information_schema')
           ORDER BY nspname, dictname"""

    def from_map(self, schema, indicts):
        """Initialize the dictionary of dictionaries by examining the input map

        :param schema: schema owning the dictionaries
        :param indicts: input YAML map defining the dictionaries
        """
        for key in indicts:
            if not key.startswith('text search dictionary '):
                raise KeyError("Unrecognized object type: %s" % key)
            tsd = key[23:]
            self[(schema.name, tsd)] = tsdict = TSDictionary(
                schema=schema.name, name=tsd)
            indict = indicts[key]
            if indict:
                for attr, val in list(indict.items()):
                    setattr(tsdict, attr, val)
                if 'oldname' in indict:
                    tsdict.oldname = indict['oldname']
                    del indict['oldname']
                if 'description' in indict:
                    tsdict.description = indict['description']


class TSParser(DbSchemaObject):
    """A text search parser definition"""

    keylist = ['schema', 'name']
    single_extern_file = True
    catalog = 'pg_ts_parser'

    @property
    def objtype(self):
        return "TEXT SEARCH PARSER"

    @commentable
    @ownable
    def create(self):
        """Return SQL statements to CREATE the parser

        :return: SQL statements
        """
        clauses = []
        for attr in ['start', 'gettoken', 'end', 'lextypes']:
            clauses.append("%s = %s" % (attr.upper(), getattr(self, attr)))
        if hasattr(self, 'headline'):
            clauses.append("HEADLINE = %s" % self.headline)
        return ["CREATE TEXT SEARCH PARSER %s (\n    %s)" % (
                self.qualname(), ',\n    '.join(clauses))]


class TSParserDict(DbObjectDict):
    "The collection of text search parsers in a database"

    cls = TSParser
    query = \
        """SELECT p.oid, nspname AS schema, prsname AS name,
                  prsstart::regproc AS start, prstoken::regproc AS gettoken,
                  prsend::regproc AS end, prslextype::regproc AS lextypes,
                  prsheadline::regproc AS headline,
                  obj_description(p.oid, 'pg_ts_parser') AS description
           FROM pg_ts_parser p
                JOIN pg_namespace n ON (prsnamespace = n.oid)
           WHERE (nspname != 'pg_catalog' AND nspname != 'information_schema')
           ORDER BY nspname, prsname"""

    def from_map(self, schema, inparsers):
        """Initialize the dictionary of parsers by examining the input map

        :param schema: schema owning the parsers
        :param inparsers: input YAML map defining the parsers
        """
        for key in inparsers:
            if not key.startswith('text search parser '):
                raise KeyError("Unrecognized object type: %s" % key)
            tsp = key[19:]
            self[(schema.name, tsp)] = parser = TSParser(
                schema=schema.name, name=tsp)
            inparser = inparsers[key]
            if inparser:
                for attr, val in list(inparser.items()):
                    setattr(parser, attr, val)
                if 'oldname' in inparser:
                    parser.oldname = inparser['oldname']
                    del inparser['oldname']
                if 'description' in inparser:
                    parser.description = inparser['description']


class TSTemplate(DbSchemaObject):
    """A text search template definition"""

    keylist = ['schema', 'name']
    single_extern_file = True
    catalog = 'pg_ts_template'

    @property
    def objtype(self):
        return "TEXT SEARCH TEMPLATE"

    @commentable
    def create(self):
        """Return SQL statements to CREATE the template

        :return: SQL statements
        """
        clauses = []
        if hasattr(self, 'init'):
            clauses.append("INIT = %s" % self.init)
        clauses.append("LEXIZE = %s" % self.lexize)
        return ["CREATE TEXT SEARCH TEMPLATE %s (\n    %s)" % (
                self.qualname(), ',\n    '.join(clauses))]


class TSTemplateDict(DbObjectDict):
    "The collection of text search templates in a database"

    cls = TSTemplate
    query = \
        """SELECT p.oid, nspname AS schema, tmplname AS name,
                  tmplinit::regproc AS init, tmpllexize::regproc AS lexize,
                  obj_description(p.oid, 'pg_ts_template') AS description
           FROM pg_ts_template p
                JOIN pg_namespace n ON (tmplnamespace = n.oid)
           WHERE (nspname != 'pg_catalog' AND nspname != 'information_schema')
           ORDER BY nspname, tmplname"""

    def from_map(self, schema, intemplates):
        """Initialize the dictionary of templates by examining the input map

        :param schema: schema owning the templates
        :param intemplates: input YAML map defining the templates
        """
        for key in intemplates:
            if not key.startswith('text search template '):
                raise KeyError("Unrecognized object type: %s" % key)
            tst = key[21:]
            self[(schema.name, tst)] = template = TSTemplate(
                schema=schema.name, name=tst)
            intemplate = intemplates[key]
            if intemplate:
                for attr, val in list(intemplate.items()):
                    setattr(template, attr, val)
                if 'oldname' in intemplate:
                    template.oldname = intemplate['oldname']
                    del intemplate['oldname']
                if 'description' in intemplate:
                    template.description = intemplate['description']
