# -*- coding: utf-8 -*-
"""
    pyrseas.dbobject.trigger
    ~~~~~~~~~~~~~~~~~~~~~~~~

    This module defines two classes: Trigger derived from
    DbSchemaObject, and TriggerDict derived from DbObjectDict.
"""
from pyrseas.dbobject import DbObjectDict, DbSchemaObject
from pyrseas.dbobject import quote_id, commentable, split_schema_obj

EXEC_PROC = 'EXECUTE PROCEDURE '
EVENT_TYPES = ['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']


class Trigger(DbSchemaObject):
    """A procedural language trigger"""

    keylist = ['schema', 'table', 'name']
    catalog = 'pg_trigger'

    def identifier(self):
        """Returns a full identifier for the trigger

        :return: string
        """
        return "%s ON %s" % (quote_id(self.name), self._table.qualname())

    def to_map(self, db):
        """Convert a trigger to a YAML-suitable format

        :return: dictionary
        """
        dct = self._base_map(db)
        if hasattr(self, 'columns'):
            dct['columns'] = [self._table.column_names()[int(k) - 1]
                              for k in self.columns.split()]
        return {self.name: dct}

    @commentable
    def create(self):
        """Return SQL statements to CREATE the trigger

        :return: SQL statements
        """
        constr = defer = ''
        if hasattr(self, 'constraint') and self.constraint:
            constr = "CONSTRAINT "
            if hasattr(self, 'deferrable') and self.deferrable:
                defer = "DEFERRABLE "
            if hasattr(self, 'initially_deferred') and self.initially_deferred:
                defer += "INITIALLY DEFERRED"
            if defer:
                defer = '\n    ' + defer
        evts = " OR ".join(self.events).upper()
        if hasattr(self, 'columns') and 'update' in self.events:
            evts = evts.replace("UPDATE", "UPDATE OF %s" % (
                ", ".join(self.columns)))
        cond = ''
        if hasattr(self, 'condition'):
            cond = "\n    WHEN (%s)" % self.condition
        return ["CREATE %sTRIGGER %s\n    %s %s ON %s%s\n    FOR EACH %s"
                "%s\n    EXECUTE PROCEDURE %s" % (
                    constr, quote_id(self.name), self.timing.upper(), evts,
                    self._table.qualname(), defer,
                    self.level.upper(), cond, self.procedure)]

    def diff_map(self, intrg):
        """Generate SQL to transform an existing trigger

        :param intrigger: a YAML map defining the new trigger
        :return: list of SQL statements

        Compares the trigger to an input trigger and generates SQL
        statements to transform it into the one represented by the
        input.
        """
        stmts = []
        attrs = ['constraint', 'deferrable', 'initially_deferred',
                 'update', 'condition', 'procedure', 'timing', 'level']

        same = True
        for attr in attrs:
            if getattr(self, attr, None) != getattr(intrg, attr, None):
                same = False
                setattr(self, attr, getattr(intrg, attr, None))

        if set(self.events) != set(intrg.events):
            same = False
            self.events = intrg.events

        if not same:
            stmts.append("DROP TRIGGER %s" % self.identifier())
            stmts.append(self.create())

        stmts.append(self.diff_privileges(intrg))
        stmts.append(self.diff_description(intrg))

        return stmts

    def get_implied_deps(self, db):
        deps = super(Trigger, self).get_implied_deps(db)

        deps.add(db.tables[self.schema, self.table])

        # short-circuit augment triggers
        if hasattr(self, '_iscfg'):
            return deps

        # the trigger procedure can have arguments, but the trigger definition
        # has always none (they are accessed through `tg_argv`).
        # TODO: this breaks if a function name contains a '('
        # (another case for a robust lookup function in db)
        fschema, fname = split_schema_obj(self.procedure, self.schema)
        if not fname.startswith('tsvector_update_trigger'):
            deps.add(db.functions[fschema, fname, ''])

        return deps

QUERY_PRE90 = \
    """SELECT t.oid,
              nspname AS schema, relname AS table,
              tgname AS name, tgisconstraint AS constraint,
              tgdeferrable AS deferrable,
              tginitdeferred AS initially_deferred,
              pg_get_triggerdef(t.oid) AS definition,
              NULL AS columns,
              obj_description(t.oid, 'pg_trigger') AS description
       FROM pg_trigger t
            JOIN pg_class c ON (t.tgrelid = c.oid)
            JOIN pg_namespace n ON (c.relnamespace = n.oid)
            JOIN pg_roles ON (n.nspowner = pg_roles.oid)
            LEFT JOIN pg_constraint cn ON (tgconstraint = cn.oid)
       WHERE contype != 'f' OR contype IS NULL
         AND (nspname != 'pg_catalog' AND nspname != 'information_schema')
       ORDER BY schema, "table", name"""


class TriggerDict(DbObjectDict):
    "The collection of triggers in a database"

    cls = Trigger
    query = \
        """SELECT t.oid,
                  nspname AS schema, relname AS table,
                  tgname AS name, pg_get_triggerdef(t.oid) AS definition,
                  CASE WHEN contype = 't' THEN true ELSE false END AS
                       constraint,
                  tgdeferrable AS deferrable,
                  tginitdeferred AS initially_deferred,
                  tgattr AS columns,
                  obj_description(t.oid, 'pg_trigger') AS description
           FROM pg_trigger t
                JOIN pg_class c ON (t.tgrelid = c.oid)
                JOIN pg_namespace n ON (c.relnamespace = n.oid)
                JOIN pg_roles ON (n.nspowner = pg_roles.oid)
                LEFT JOIN pg_constraint cn ON (tgconstraint = cn.oid)
           WHERE NOT tgisinternal
             AND (nspname != 'pg_catalog' AND nspname != 'information_schema')
           ORDER BY schema, "table", name"""

    def _from_catalog(self):
        """Initialize the dictionary of triggers by querying the catalogs"""
        if self.dbconn.version < 90000:
            self.query = QUERY_PRE90
        for trig in self.fetch():
            for timing in ['BEFORE', 'AFTER', 'INSTEAD OF']:
                timspc = timing + ' '
                if timspc in trig.definition:
                    trig.timing = timing.lower()
                    evtstart = trig.definition.index(timspc) + len(timspc)
            evtend = trig.definition.index(' ON ', evtstart)
            events = trig.definition[evtstart:evtend]
            trig.events = []
            for evt in EVENT_TYPES:
                if evt in events:
                    trig.events.append(evt.lower())
            trig.level = ('FOR EACH ROW' in trig.definition and 'row' or
                          'statement')
            if 'WHEN (' in trig.definition:
                trig.condition = trig.definition[
                    trig.definition.index('WHEN (') + 6:
                    trig.definition.index(') EXECUTE PROCEDURE')]
            trig.procedure = trig.definition[trig.definition.index(EXEC_PROC) +
                                             len(EXEC_PROC):]
            del trig.definition
            self.by_oid[trig.oid] = self[trig.key()] = trig

    def from_map(self, table, intriggers):
        """Initalize the dictionary of triggers by converting the input map

        :param table: table owning the triggers
        :param intriggers: YAML map defining the triggers
        """
        for trg in intriggers:
            intrig = intriggers[trg]
            if not intrig:
                raise ValueError("Trigger '%s' has no specification" % trg)
            self[(table.schema, table.name, trg)] = trig = Trigger(
                schema=table.schema, table=table.name, name=trg)
            for attr, val in list(intrig.items()):
                setattr(trig, attr, val)
            if not hasattr(trig, 'level'):
                trig.level = 'statement'
            if 'oldname' in intrig:
                trig.oldname = intrig['oldname']
            if 'description' in intrig:
                trig.description = intrig['description']
