import logging
import os

import ckan.plugins as p
from ckan import model
from ckan.lib.plugins import DefaultOrganizationForm, DefaultGroupForm

from ckanext.hierarchy.logic import action
from ckanext.hierarchy import helpers

log = logging.getLogger(__name__)
g = p.toolkit.g
c = p.toolkit.c

# This plugin is designed to work only these versions of CKAN
p.toolkit.check_ckan_version(min_version='2.0')


def custom_convert_from_extras(key, data, errors, context):
    '''Converts values from extras, tailored for groups.'''

    # Set to empty string to remove Missing objects
    data[key] = ""

    to_remove = []
    for data_key in list(data.keys()):
        if (data_key[0] == 'extras'):
            data_value = data[data_key]
            if 'key' in data_value and data_value['key'] == key[-1]:
                data[key] = data_value['value']
                to_remove.append(data_key)
                break
    else:
        return

    for remove_key in to_remove:
        del data[remove_key]


class HierarchyDisplay(p.SingletonPlugin):
    p.implements(p.IConfigurer, inherit=True)
    p.implements(p.IActions, inherit=True)
    p.implements(p.ITemplateHelpers, inherit=True)
    p.implements(p.IPackageController, inherit=True)

    # IConfigurer

    def update_config(self, config):
        p.toolkit.add_template_directory(config, 'templates')
        p.toolkit.add_public_directory(config, 'fanstatic')
        p.toolkit.add_resource('fanstatic', 'hierarchy')

        try:
            from ckan.lib.webassets_tools import add_public_path
        except ImportError:
            pass
        else:
            asset_path = os.path.join(
                os.path.dirname(__file__), 'fanstatic'
            )
            add_public_path(asset_path, '/')

    # IActions

    def get_actions(self):
        return {'group_tree': action.group_tree,
                'group_tree_section': action.group_tree_section,
                }

    # ITemplateHelpers
    def get_helpers(self):
        return {'group_tree': helpers.group_tree,
                'group_tree_section': helpers.group_tree_section,
                'group_tree_parents': helpers.group_tree_parents,
                'group_tree_get_longname': helpers.group_tree_get_longname,
                'group_tree_highlight': helpers.group_tree_highlight,
                'get_allowable_parent_groups':
                helpers.get_allowable_parent_groups,
                'is_include_children_selected':
                helpers.is_include_children_selected,
                }

    # IPackageController

    def before_dataset_search(self, search_params):
        '''When searching an organization, optionally extend the search any
        sub-organizations too. This is achieved by modifying the search options
        before they go to SOLR.
        '''
        # Check if we're called from the organization controller, as detected
        # by g being registered for this thread, and the existence of g.fields
        # values

        try:
            if not isinstance(g.fields, list) and not hasattr(g, 'fields'):
                return search_params
        except (TypeError, AttributeError, RuntimeError):
            # it's non-organization controller or CLI call
            return search_params

        # e.g. search_params['q'] = u' owner_org:"id" include_children: "True"'
        query = search_params.get('q', '')
        fq = search_params.get('fq', '')

        include_children = query and 'include_children: "True"' in query

        if include_children or helpers.is_include_children_selected():

            # get a list of all the children organizations and include them in
            # the search params
            children_org_hierarchy = model.Group.get(g.group_dict.get('id')).\
                get_children_group_hierarchy(type='organization')
            children_names = [org[1] for org in children_org_hierarchy]
            # remove include_children clause - it is a message for this func,
            # not solr
            # CKAN<=2.7 it's in the q field:
            query = query.replace('include_children: "True"', '')
            # CKAN=2.8.x it's in the fq field:
            fq = fq.replace('include_children:"True"', '')

            if children_names:
                # remove existing owner_org:"<parent>" clause - we'll replace
                # it with the tree of orgs in a moment.
                owner_org_q = 'owner_org:"{}"'.format(g.group_dict.get('id'))
                # CKAN<=2.7 it's in the q field:
                query = query.replace(owner_org_q, '')
                # CKAN=2.8.x it's in the fq field:
                fq = fq.replace(owner_org_q, '')
                # add the org clause
                query = query.strip()
                if query:
                    query += ' AND '
                query += '({})'.format(
                    ' OR '.join(
                        'organization:{}'.format(org_name)
                        for org_name in [g.group_dict.get('name')] +
                        children_names))

            search_params['q'] = query.strip()
            search_params['fq'] = fq
            # remove include_children from the filter-list - we have a checkbox
            g.fields_grouped.pop('include_children', None)

        if c.group_dict.get('type') == 'group':
            group_selected = model.Group.get(c.group_dict.get('id'))
            group_with_children = ' OR '.join(
                '{}'.format(grp.name)
                for grp in group_selected.get_children_groups('group') + [group_selected]
            )
            groups_fq = 'groups:({})'.format(group_with_children)
            search_params['fq'] = fq.replace(
                'groups:"{}"'.format(group_selected.name),
                groups_fq
            )
        return search_params

    def before_search(self, search_params):
        return self.before_dataset_search(search_params)


class HierarchyForm(p.SingletonPlugin, DefaultOrganizationForm):
    p.implements(p.IGroupForm, inherit=True)

    # IGroupForm

    def group_types(self):
        return ('organization',)

    def group_controller(self):
        return 'organization'

    def setup_template_variables(self, context, data_dict):
        group_id = data_dict.get('id')
        g.allowable_parent_groups = \
            helpers.get_allowable_parent_groups(group_id)


class HierarchyGroupForm(p.SingletonPlugin, DefaultGroupForm):
    p.implements(p.IGroupForm, inherit=True)

    # IGroupForm

    def group_types(self):
        return ('group',)

    def setup_template_variables(self, context, data_dict):
        group_id = data_dict.get('id')
        g.allowable_parent_groups = \
            helpers.get_allowable_parent_groups(group_id)
