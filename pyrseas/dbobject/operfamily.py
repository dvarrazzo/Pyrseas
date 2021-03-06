# -*- coding: utf-8 -*-
"""
    pyrseas.dbobject.operfamily
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~

    This module defines two classes: OperatorFamily derived from
    DbSchemaObject and OperatorFamilyDict derived from DbObjectDict.
"""
from pyrseas.dbobject import DbObjectDict, DbSchemaObject
from pyrseas.dbobject import commentable, ownable, split_schema_obj


class OperatorFamily(DbSchemaObject):
    """An operator family"""

    keylist = ['schema', 'name', 'index_method']
    single_extern_file = True
    catalog = 'pg_opfamily'

    def __init__(self, name, schema, index_method, description, owner,
                 oid=None):
        """Initialize the operator family

        :param name: operator name (from opfname)
        :param schema: schema name (from opfnamespace)
        :param index_method: index access method (from amname via opfmethod)
        :param description: comment text (from obj_description())
        :param owner: owner name (from rolname via opfowner)
        """
        super(OperatorFamily, self).__init__(name, schema, description)
        self._init_own_privs(owner, [])
        self.index_method = index_method
        self.oid = oid

    @property
    def objtype(self):
        return "OPERATOR FAMILY"

    def extern_key(self):
        """Return the key to be used in external maps for the operator family

        :return: string
        """
        return '%s %s using %s' % (self.objtype.lower(), self.name,
                                   self.index_method)

    def identifier(self):
        """Return a full identifier for an operator family object

        :return: string
        """
        return "%s USING %s" % (self.qualname(), self.index_method)

    @commentable
    @ownable
    def create(self):
        """Return SQL statements to CREATE the operator family

        :return: SQL statements
        """
        return ["CREATE OPERATOR FAMILY %s USING %s" % (
                self.qualname(), self.index_method)]


class OperatorFamilyDict(DbObjectDict):
    "The collection of operator families in a database"

    cls = OperatorFamily
    query = \
        """SELECT o.oid,
                  nspname AS schema, opfname AS name, rolname AS owner,
                  amname AS index_method,
                  obj_description(o.oid, 'pg_opfamily') AS description
           FROM pg_opfamily o
                JOIN pg_roles r ON (r.oid = opfowner)
                JOIN pg_am a ON (opfmethod = a.oid)
                JOIN pg_namespace n ON (opfnamespace = n.oid)
           WHERE (nspname != 'pg_catalog' AND nspname != 'information_schema')
             AND o.oid NOT IN (
                 SELECT objid FROM pg_depend WHERE deptype = 'e'
                              AND classid = 'pg_opfamily'::regclass)
           ORDER BY opfnamespace, opfname, amname"""

    def from_map(self, schema, inopfams):
        """Initalize the dict of operator families by converting the input map

        :param schema: schema owning the operators
        :param inopfams: YAML map defining the operator families
        """
        for key in inopfams:
            if not key.startswith('operator family ') or ' using ' not in key:
                raise KeyError("Unrecognized object type: %s" % key)
            pos = key.rfind(' using ')
            opf = key[16:pos]  # 16 = len('operator family ')
            idx = key[pos + 7:]  # 7 = len(' using ')
            inopfam = inopfams[key]
            self[(schema.name, opf, idx)] = opfam = OperatorFamily(
                opf, schema.name, idx, inopfam.pop('description', None),
                inopfam.pop('owner', None))
            if 'oldname' in inopfam:
                opfam.oldname = inopfam.get('oldname')

    def find(self, obj, meth):
        schema, name = split_schema_obj(obj)
        return self.get((schema, name, meth))
