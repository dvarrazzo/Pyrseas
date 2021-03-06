# -*- coding: utf-8 -*-
"""
    pyrseas.dbobject.function
    ~~~~~~~~~~~~~~~~~~~~~~~~~

    This module defines four classes: Proc derived from
    DbSchemaObject, Function and Aggregate derived from Proc, and
    FunctionDict derived from DbObjectDict.
"""
from pyrseas.dbobject import DbObjectDict, DbSchemaObject
from pyrseas.dbobject import commentable, ownable, grantable, split_schema_obj
from pyrseas.dbobject.privileges import privileges_from_map

VOLATILITY_TYPES = {'i': 'immutable', 's': 'stable', 'v': 'volatile'}


class Proc(DbSchemaObject):
    """A procedure such as a FUNCTION or an AGGREGATE"""

    keylist = ['schema', 'name', 'arguments']
    catalog = 'pg_proc'

    @property
    def allprivs(self):
        return 'X'

    def extern_key(self):
        """Return the key to be used in external maps for this function

        :return: string
        """
        return '%s %s(%s)' % (self.objtype.lower(), self.name, self.arguments)

    def identifier(self):
        """Return a full identifier for a function object

        :return: string
        """
        return "%s(%s)" % (self.qualname(), self.arguments)

    def get_implied_deps(self, db):
        # List the previous dependencies
        deps = super(Proc, self).get_implied_deps(db)

        # Add back the language
        if getattr(self, 'language', None):
            lang = db.languages.get(self.language)
            if lang:
                deps.add(lang)

        # Add back the types
        if self.arguments:
            for arg in self.arguments.split(', '):
                arg = db.find_type(arg.split()[-1])
                if arg is not None:
                    deps.add(arg)

        return deps


class Function(Proc):
    """A procedural language function"""

    def to_map(self, db, no_owner, no_privs):
        """Convert a function to a YAML-suitable format

        :param no_owner: exclude function owner information
        :param no_privs: exclude privilege information
        :return: dictionary
        """
        dct = self._base_map(db, no_owner, no_privs)
        if self.volatility == 'v':
            del dct['volatility']
        else:
            dct['volatility'] = VOLATILITY_TYPES[self.volatility]
        if hasattr(self, 'obj_file'):
            dct['link_symbol'] = self.source
            del dct['source']
        if hasattr(self, 'cost') and self.cost != 0:
            if self.language in ['c', 'internal']:
                if self.cost == 1:
                    del dct['cost']
            else:
                if self.cost == 100:
                    del dct['cost']
        if hasattr(self, 'rows') and self.rows != 0:
            if self.rows == 1000:
                del dct['rows']

        return dct

    @commentable
    @grantable
    @ownable
    def create(self, newsrc=None, basetype=False):
        """Return SQL statements to CREATE or REPLACE the function

        :param newsrc: new source for a changed function
        :return: SQL statements
        """
        stmts = []
        if hasattr(self, 'obj_file'):
            src = "'%s', '%s'" % (self.obj_file,
                                  hasattr(self, 'link_symbol') and
                                  self.link_symbol or self.name)
        elif self.language == 'internal':
            src = "$$%s$$" % (newsrc or self.source)
        else:
            src = "$_$%s$_$" % (newsrc or self.source)
        volat = leakproof = strict = secdef = cost = rows = config = ''
        if hasattr(self, 'volatility'):
            volat = ' ' + VOLATILITY_TYPES[self.volatility].upper()
        if hasattr(self, 'leakproof') and self.leakproof is True:
            leakproof = ' LEAKPROOF'
        if hasattr(self, 'strict') and self.strict:
            strict = ' STRICT'
        if hasattr(self, 'security_definer') and self.security_definer:
            secdef = ' SECURITY DEFINER'
        if hasattr(self, 'configuration'):
            config = ' SET %s' % self.configuration[0]
        if hasattr(self, 'cost') and self.cost != 0:
            if self.language in ['c', 'internal']:
                if self.cost != 1:
                    cost = " COST %s" % self.cost
            else:
                if self.cost != 100:
                    cost = " COST %s" % self.cost
        if hasattr(self, 'rows') and self.rows != 0:
            if self.rows != 1000:
                rows = " ROWS %s" % self.rows

        # We may have to create a shell type if we are its input or output
        # functions
        t = getattr(self, '_defining', None)
        if t is not None:
            if not hasattr(t, '_shell_created'):
                t._shell_created = True
                stmts.append("CREATE TYPE %s" % t.qualname())

        # TODO: Add a single "SET check_function_bodies = false"
        #       before the first CREATE FUNCTION

        args = self.allargs if hasattr(self, 'allargs') else self.arguments
        stmts.append("CREATE%s FUNCTION %s(%s) RETURNS %s\n    LANGUAGE %s"
                     "%s%s%s%s%s%s%s\n    AS %s" % (
                         newsrc and " OR REPLACE" or '', self.qualname(),
                         args, self.returns, self.language, volat, leakproof,
                         strict, secdef, cost, rows, config, src))
        return stmts

    def alter(self, infunction, no_owner=False):
        """Generate SQL to transform an existing function

        :param infunction: a YAML map defining the new function
        :return: list of SQL statements

        Compares the function to an input function and generates SQL
        statements to transform it into the one represented by the
        input.
        """
        stmts = []
        if hasattr(self, 'source') and hasattr(infunction, 'source'):
            if self.source != infunction.source:
                stmts.append(self.create(infunction.source))
        if hasattr(self, 'leakproof') and self.leakproof is True:
            if hasattr(infunction, 'leakproof') and \
                    infunction.leakproof is True:
                stmts.append("ALTER FUNCTION %s LEAKPROOF" % self.identifier())
            else:
                stmts.append("ALTER FUNCTION %s NOT LEAKPROOF"
                             % self.identifier())
        elif hasattr(infunction, 'leakproof') and infunction.leakproof is True:
            stmts.append("ALTER FUNCTION %s LEAKPROOF" % self.qualname())
        stmts.append(super(Function, self).alter(infunction,
                                                 no_owner=no_owner))
        return stmts

    def get_implied_deps(self, db):
        # List the previous dependencies
        deps = super(Function, self).get_implied_deps(db)

        # Add back the return type
        rettype = self.returns
        if rettype.upper().startswith("SETOF "):
            rettype = rettype.split(None, 1)[-1]
        rettype = db.find_type(rettype)
        if rettype is not None:
            deps.add(rettype)

        return deps

    def get_deps(self, db):
        deps = super(Function, self).get_deps(db)

        # avoid circular import dependencies
        from pyrseas.dbobject.dbtype import DbType

        # drop the dependency on the type if this function is an in/out
        # because there is a loop here.
        for dep in list(deps):
            if isinstance(dep, DbType):
                for attr in ('input', 'output', 'send', 'receive'):
                    fname = getattr(dep, attr, None)
                    if fname and fname == self.qualname():
                        deps.remove(dep)
                        self._defining = dep    # we may need a shell for this
                        break

        return deps

    def drop(self):
        # If the function defines a type it will be dropped by the CASCADE
        # on the type.
        if getattr(self, '_defining', None):
            return []
        else:
            return super(Function, self).drop()


class Aggregate(Proc):
    """An aggregate function"""

    def to_map(self, db, no_owner, no_privs):
        """Convert an agggregate to a YAML-suitable format

        :param no_owner: exclude aggregate owner information
        :param no_privs: exclude privilege information
        :return: dictionary
        """
        dct = self._base_map(db, no_owner, no_privs)
        del dct['language']
        return dct

    @commentable
    @grantable
    @ownable
    def create(self):
        """Return SQL statements to CREATE the aggregate

        :return: SQL statements
        """
        opt_clauses = []
        if hasattr(self, 'finalfunc'):
            opt_clauses.append("FINALFUNC = %s" % self.finalfunc)
        if hasattr(self, 'initcond'):
            opt_clauses.append("INITCOND = '%s'" % self.initcond)
        if hasattr(self, 'sortop'):
            opt_clauses.append("SORTOP = %s" % self.sortop)
        return ["CREATE AGGREGATE %s(%s) (\n    SFUNC = %s,"
                "\n    STYPE = %s%s%s)" % (
                    self.qualname(), self.arguments, self.sfunc, self.stype,
                    opt_clauses and ',\n    ' or '',
                    ',\n    '.join(opt_clauses))]

    def get_implied_deps(self, db):
        # List the previous dependencies
        deps = super(Aggregate, self).get_implied_deps(db)

        sch, fnc = split_schema_obj(self.sfunc)
        args = self.stype + ', ' + self.arguments
        deps.add(db.functions[sch, fnc, args])
        if hasattr(self, 'finalfunc'):
            sch, fnc = split_schema_obj(self.finalfunc)
            deps.add(db.functions[sch, fnc, self.stype])

        return deps

QUERY_PRE92 = \
    """SELECT p.oid,
              nspname AS schema, proname AS name,
              pg_get_function_identity_arguments(p.oid) AS arguments,
              pg_get_function_arguments(p.oid) AS allargs,
              pg_get_function_result(p.oid) AS returns,
              rolname AS owner, array_to_string(proacl, ',') AS privileges,
              l.lanname AS language, provolatile AS volatility,
              proisstrict AS strict, proisagg, prosrc AS source,
              probin::text AS obj_file, proconfig AS configuration,
              prosecdef AS security_definer, procost AS cost,
              aggtransfn::regproc AS sfunc, aggtranstype::regtype AS stype,
              aggfinalfn::regproc AS finalfunc,
              agginitval AS initcond, aggsortop::regoper AS sortop,
              obj_description(p.oid, 'pg_proc') AS description,
              prorows::integer AS rows
       FROM pg_proc p
            JOIN pg_roles r ON (r.oid = proowner)
            JOIN pg_namespace n ON (pronamespace = n.oid)
            JOIN pg_language l ON (prolang = l.oid)
            LEFT JOIN pg_aggregate a ON (p.oid = aggfnoid)
       WHERE (nspname != 'pg_catalog' AND nspname != 'information_schema')
         AND p.oid NOT IN (
             SELECT objid FROM pg_depend WHERE deptype = 'e'
                          AND classid = 'pg_proc'::regclass)
       ORDER BY nspname, proname"""


class ProcDict(DbObjectDict):
    "The collection of regular and aggregate functions in a database"

    cls = Proc
    query = \
        """SELECT p.oid,
                  nspname AS schema, proname AS name,
                  pg_get_function_identity_arguments(p.oid) AS arguments,
                  pg_get_function_arguments(p.oid) AS allargs,
                  pg_get_function_result(p.oid) AS returns,
                  rolname AS owner, array_to_string(proacl, ',') AS privileges,
                  l.lanname AS language, provolatile AS volatility,
                  proisstrict AS strict, proisagg, prosrc AS source,
                  probin::text AS obj_file, proconfig AS configuration,
                  prosecdef AS security_definer, procost AS cost,
                  proleakproof AS leakproof,
                  aggtransfn::regproc AS sfunc, aggtranstype::regtype AS stype,
                  aggfinalfn::regproc AS finalfunc,
                  agginitval AS initcond, aggsortop::regoper AS sortop,
                  obj_description(p.oid, 'pg_proc') AS description,
                  prorows::integer AS rows
           FROM pg_proc p
                JOIN pg_roles r ON (r.oid = proowner)
                JOIN pg_namespace n ON (pronamespace = n.oid)
                JOIN pg_language l ON (prolang = l.oid)
                LEFT JOIN pg_aggregate a ON (p.oid = aggfnoid)
           WHERE (nspname != 'pg_catalog' AND nspname != 'information_schema')
             AND p.oid NOT IN (
                 SELECT objid FROM pg_depend WHERE deptype = 'e'
                              AND classid = 'pg_proc'::regclass)
           ORDER BY nspname, proname"""

    def _from_catalog(self):
        """Initialize the dictionary of procedures by querying the catalogs"""
        if self.dbconn.version < 90200:
            self.query = QUERY_PRE92
        for proc in self.fetch():
            sch, prc, arg = proc.key()
            oid = proc.oid
            if hasattr(proc, 'allargs') and proc.allargs == proc.arguments:
                del proc.allargs
            if hasattr(proc, 'proisagg'):
                del proc.proisagg
                del proc.source
                del proc.volatility
                del proc.returns
                del proc.cost
                if proc.finalfunc == '-':
                    del proc.finalfunc
                if proc.sortop == '0':
                    del proc.sortop
                self.by_oid[oid] = self[sch, prc, arg] \
                    = Aggregate(**proc.__dict__)
            else:
                self.by_oid[oid] = self[sch, prc, arg] \
                    = Function(**proc.__dict__)

    def from_map(self, schema, infuncs):
        """Initalize the dictionary of functions by converting the input map

        :param schema: schema owning the functions
        :param infuncs: YAML map defining the functions
        """
        for key in infuncs:
            (objtype, spc, fnc) = key.partition(' ')
            if spc != ' ' or objtype not in ['function', 'aggregate']:
                raise KeyError("Unrecognized object type: %s" % key)
            paren = fnc.find('(')
            if paren == -1 or fnc[-1:] != ')':
                raise KeyError("Invalid function signature: %s" % fnc)
            arguments = fnc[paren + 1:-1]
            infunc = infuncs[key]
            fnc = fnc[:paren]
            if objtype == 'function':
                self[(schema.name, fnc, arguments)] = func = Function(
                    schema=schema.name, name=fnc, arguments=arguments)
            else:
                self[(schema.name, fnc, arguments)] = func = Aggregate(
                    schema=schema.name, name=fnc, arguments=arguments)
                func.language = 'internal'
            if not infunc:
                raise ValueError("Function '%s' has no specification" % fnc)
            for attr in infunc:
                setattr(func, attr, infunc[attr])
            if hasattr(func, 'volatility'):
                func.volatility = func.volatility[:1].lower()
            if isinstance(func, Function):
                src = hasattr(func, 'source')
                obj = hasattr(func, 'obj_file')
                if (src and obj) or not (src or obj):
                    raise ValueError("Function '%s': either source or "
                                     "obj_file must be specified" % fnc)
            if 'privileges' in infunc:
                func.privileges = privileges_from_map(
                    infunc['privileges'], func.allprivs, func.owner)

    def find(self, func, args):
        """Return a function given its name and arguments

        :param func: name of the function, eventually with schema
        :param args: list of type names

        Return the function found, else None.
        """
        schema, name = split_schema_obj(func)
        args = ', '.join(args)
        return self.get((schema, name, args))

    def link_refs(self, dbtypes, dbeventtrigs):
        """Connect the functions to other objects

        - Connect event triggers to the functions executed
        - Connect defining functions to the type they define

        :param dbtypes: dictionary of types
        :param dbeventtrigs: dictionary of event triggers

        Fills in the `event_triggers` list for each function by
        traversing the `dbeventtrigs` dictionary.
        """
        for key in dbeventtrigs:
            evttrg = dbeventtrigs[key]
            (sch, fnc) = split_schema_obj(evttrg.procedure)
            func = self[(sch, fnc[:-2], '')]
            if not hasattr(func, 'event_triggers'):
                func.event_triggers = []
            func.event_triggers.append(evttrg.name)

        # TODO: this link is needed from map, not from sql.
        # is this a pattern? I was assuming link_refs would have disappeared
        # but I'm actually still maintaining them. Verify if they are always
        # only used for from_map, not for from_catalog
        for key in dbtypes:
            t = dbtypes[key]
            for f in t.find_defining_funcs(self):
                f._defining = t
