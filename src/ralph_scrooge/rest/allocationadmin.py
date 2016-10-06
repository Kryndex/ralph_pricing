#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from decimal import Decimal as D

from django.db.transaction import commit_on_success
from rest_framework.views import APIView
from rest_framework.response import Response

from ralph_scrooge.rest.common import get_dates
from ralph_scrooge.models import (
    DynamicExtraCost,
    DynamicExtraCostType,
    ExtraCost,
    ExtraCostType,
    ServiceEnvironment,
    Team,
    TeamCost,
    UsagePrice,
    UsageType,
    Warehouse,
)
from ralph_scrooge.csvutil import parse_csv


class NoUsageTypeError(Exception):
    pass


class NoDynamicExtraCostTypeError(Exception):
    pass


class TeamDoesNotExistError(Exception):
    pass


class NoExtraCostTypeError(Exception):
    pass


class NoExtraCostError(Exception):
    pass


class ServiceEnvironmentDoesNotExistError(Exception):
    pass


def get_allocationadmin_from_file(file):
    """
    Parse CSV files from Python File object (file())
    It then search ServiceEnvironment based on the values in the service field.
    Returns list of usages (compatible with JSON sent by Scroge GUI)

    Args:
        file: Python File Object with structures:
            cost;forecast_cost;service_uid or service_env_id;environment
            1;1;sc-001;prod
    Return:
        list: Example data:
            [
                {
                    'service': service_environment,
                    'env': service_environment,
                    'forecast_cost': '1',
                    'cost': '1'
                },
                ...
            ]
    """
    file_results = []
    data_results = parse_csv(file)
    errors = []
    for row in data_results:
        query = {}
        if row.get('service_env_id'):
            query['pk'] = row['service_env_id']
        else:
            if row.get('service_uid'):
                query['service__ci_uid'] = row['service_uid']
            else:
                query['service__name'] = row['service_name']

            query['environment__name'] = row['environment']

        try:
            service_env = ServiceEnvironment.objects.get(**query)
        except ServiceEnvironment.DoesNotExist:
            error = (
                'Service environment for service: {}, environment: '
                '{} does not exist.'
            ).format(
                row.get('service_uid', row.get('service_name')),
                row['environment']
            )
            errors.append(error)
            service_env = ''

        row_data = {
            'service': service_env,
            'env': service_env,
            'forecast_cost': row['forecast_cost'],
            'cost': row['cost']
        }
        if len(row.get('id', '')) > 1:
            row_data.update({'id': row['id']})
        file_results.append(row_data)

    return (file_results, errors)


class AllocationAdminContent(APIView):
    def _get_extra_costs(self, start, end):
        rows = []
        for extra_cost_type in ExtraCostType.objects.all():
            extra_costs = []
            for extra_cost in ExtraCost.objects.filter(
                extra_cost_type=extra_cost_type,
                start=start,
                end=end,
            ).select_related('service_environment'):
                extra_costs.append({
                    'id': extra_cost.id,
                    'cost': round(extra_cost.cost, 2),
                    'forecast_cost': round(extra_cost.forecast_cost, 2),
                    'service': extra_cost.service_environment.service_id,
                    'env': extra_cost.service_environment.environment_id
                })
            rows.append({
                'extra_cost_type': {
                    'id': extra_cost_type.id,
                    'name': extra_cost_type.name,
                },
                'extra_costs': extra_costs
            })
        return rows

    def _get_dynamic_extra_costs(self, start, end):
        rows = []
        for dynamic_extra_cost_type in DynamicExtraCostType.objects.all():
            try:
                cost, forecast_cost = DynamicExtraCost.objects.filter(
                    dynamic_extra_cost_type=dynamic_extra_cost_type,
                    start=start,
                    end=end,
                ).values_list('cost', 'forecast_cost')[0]
            except IndexError:
                cost, forecast_cost = D(0), D(0)
            rows.append({
                'dynamic_extra_cost_type': {
                    'id': dynamic_extra_cost_type.id,
                    'name': dynamic_extra_cost_type.name,
                },
                'cost': round(cost, 2),
                'forecast_cost': round(forecast_cost, 2)
            })
        return rows

    def _get_team_costs(self, start, end):
        rows = []
        for team in Team.objects.all():
            try:
                members, cost, forecast_cost = TeamCost.objects.filter(
                    team=team,
                    start=start,
                    end=end,
                ).values_list('members_count', 'cost', 'forecast_cost')[0]
            except IndexError:
                members, cost, forecast_cost = 0, D(0), D(0)
            rows.append({
                'team': {
                    'id': team.id,
                    'name': team.name,
                },
                'cost': round(cost, 2),
                'forecast_cost': round(forecast_cost, 2),
                'members': members,
            })
        return rows

    def _get_base_usages(self, start, end):
        rows = []
        warehouses = Warehouse.objects.filter(
            show_in_report=True,
        )
        for usage_type in UsageType.objects.filter(
            usage_type='BU',
            is_manually_type=True,
        ):
            if not usage_type.by_warehouse:
                try:
                    cost, forecast_cost = UsagePrice.objects.filter(
                        type=usage_type,
                        start=start,
                        end=end,
                    ).values_list('cost', 'forecast_cost')[0]
                except IndexError:
                    cost, forecast_cost = D(0), D(0)
                rows.append({
                    'type': {
                        'id': usage_type.id,
                        'name': usage_type.name,
                    },
                    'cost': round(cost, 2),
                    'forecast_cost': round(forecast_cost, 2)
                })
            else:
                for warehouse in warehouses:
                    try:
                        cost, forecast_cost = UsagePrice.objects.filter(
                            type=usage_type,
                            start=start,
                            end=end,
                            warehouse=warehouse,
                        ).values_list('cost', 'forecast_cost')[0]
                    except IndexError:
                        cost, forecast_cost = D(0), D(0)
                    rows.append({
                        'type': {
                            'id': usage_type.id,
                            'name': usage_type.name,
                        },
                        'cost': round(cost, 2),
                        'forecast_cost': round(forecast_cost, 2),
                        'warehouse': {
                            'id': warehouse.id,
                            'name': warehouse.name,
                        }
                    })
        return rows

    def get(self, request, month, year, format=None):
        first_day, last_day, days_in_month = get_dates(year, month)
        base_usages = self._get_base_usages(first_day, last_day)
        team_costs = self._get_team_costs(first_day, last_day)
        dynamic_extra_costs = self._get_dynamic_extra_costs(
            first_day,
            last_day,
        )
        extra_costs = self._get_extra_costs(first_day, last_day)
        return Response({
            'baseusages': {
                'name': 'Base Usages',
                'rows': base_usages,
                'template': 'tabbaseusages.html',
            },
            'teamcosts': {
                'name': 'Team Costs',
                'rows': team_costs,
                'template': 'tabteamcosts.html',
            },
            'dynamicextracosts': {
                'name': 'Dynamic Extra Costs',
                'rows': dynamic_extra_costs,
                'template': 'tabdynamicextracosts.html',
            },
            'extracosts': {
                'name': 'Extra Costs',
                'rows': extra_costs,
                'template': 'tabextracostsadmin.html',
            },
        })

    def _save_base_usages(self, start, end, post_data):
        for row in post_data['rows']:
            try:
                usage_type = UsageType.objects_admin.get(id=row['type']['id'])
            except UsageType.DoesNotExist:
                raise NoUsageTypeError(
                    'No usage type with id {0}'.format(row['type']['id'])
                )

            params = {
                "type": usage_type,
                "start": start,
                "end": end,
            }
            if 'warehouse' in row:
                params.update({"warehouse": Warehouse.objects.get(
                    id=row['warehouse']['id']
                )})

            usage_price = UsagePrice.objects.get_or_create(**params)[0]
            usage_price.cost = row.get('cost', 0)
            usage_price.forecast_cost = row.get('forecast_cost', 0)
            usage_price.save()

    def _save_extra_costs(self, start, end, post_data):
        saved_costs = []
        for row in post_data['rows']:
            try:
                extra_cost_type = ExtraCostType.objects_admin.get(
                    id=row['extra_cost_type']['id'],
                )
            except ExtraCostType.DoesNotExist:
                raise NoExtraCostTypeError(
                    'No extra cost type with id {0}'.format(
                        row['extra_cost_type']['id']
                    )
                )
            for ec_row in row['extra_costs']:
                if ('service' in ec_row and
                        'env' in ec_row and
                        ec_row['service'] and
                        ec_row['env']):
                    if isinstance(ec_row['service'], ServiceEnvironment):
                        service_environment = ec_row['service']
                    else:
                        try:
                            service_environment = ServiceEnvironment.objects.get(  # noqa
                                service_id=ec_row['service'],
                                environment_id=ec_row['env']
                            )
                        except ServiceEnvironment.DoesNotExist:
                            raise ServiceEnvironmentDoesNotExistError((
                                'Service environment does not exist for '
                                'service with ID {0} and environment with '
                                'ID {1}'
                            ).format(
                                ec_row['service'],
                                ec_row['env']
                            ))
                    if 'id' in ec_row:
                        try:
                            extra_cost = ExtraCost.objects.get(
                                id=ec_row['id']
                            )
                        except ExtraCost.DoesNotExist:
                            raise NoExtraCostError(
                                'Extra cost with id {0}'
                                ' does not exist'.format(
                                    ec_row['id']
                                )
                            )
                        extra_cost.cost = ec_row['cost']
                        extra_cost.forecast_cost = ec_row['forecast_cost']
                        extra_cost.save()
                    else:
                        extra_cost = ExtraCost.objects.create(
                            extra_cost_type=extra_cost_type,
                            service_environment=service_environment,
                            start=start,
                            end=end,
                            cost=ec_row['cost'],
                            forecast_cost=ec_row['forecast_cost']
                        )
                    saved_costs.append(extra_cost.id)
        # delete extra costs that were missing in the form
        ExtraCost.objects.filter(start=start, end=end).exclude(
            pk__in=saved_costs
        ).delete()

    def _save_dynamic_extra_costs(self, start, end, post_data):
        for row in post_data['rows']:
            try:
                dynamic_extra_cost_type =\
                    DynamicExtraCostType.objects_admin.get(
                        id=row['dynamic_extra_cost_type']['id'],
                    )
            except DynamicExtraCostType.DoesNotExist:
                raise NoDynamicExtraCostTypeError(
                    'No dynamic extra cost type with id {0}'.format(
                        row['dynamic_extra_cost_type']['id']
                    )
                )
            dynamic_extra_cost = DynamicExtraCost.objects.get_or_create(
                dynamic_extra_cost_type=dynamic_extra_cost_type,
                start=start,
                end=end,
                defaults=dict(
                    cost=row['cost'],
                    forecast_cost=row['forecast_cost']
                )
            )[0]
            dynamic_extra_cost.cost = row['cost']
            dynamic_extra_cost.forecast_cost = row['forecast_cost']
            dynamic_extra_cost.save()

    def _save_team_costs(self, start, end, post_data):
        for row in post_data['rows']:
            try:
                team = Team.objects.get(id=row['team']['id'])
            except Team.DoesNotExist:
                raise TeamDoesNotExistError(
                    "Team with id {0} does not exist".format(
                        row['team']['id']
                    )
                )
            team_cost = TeamCost.objects.get_or_create(
                team=team,
                start=start,
                end=end,
            )[0]
            team_cost.cost = row['cost']
            team_cost.forecast_cost = row['forecast_cost']
            team_cost.members_count = row['members']
            team_cost.save()

    @commit_on_success()
    def post(self, request, year, month, allocate_type, *args, **kwargs):
        if request.FILES and allocate_type == 'extracosts':
            rows, errors = get_allocationadmin_from_file(request.FILES['file'])
            if errors:
                return Response({'status': False, 'errors': errors})

            post_data = {
                'rows': [{
                    'extra_cost_type': {
                        'id': int(request.POST['extra_cost_type_id'])
                    },
                    'extra_costs': rows
                }]
            }
        else:
            post_data = request.DATA

        first_day, last_day, days_in_month = get_dates(year, month)
        if allocate_type == 'baseusages':
            self._save_base_usages(first_day, last_day, post_data)
        if allocate_type == 'extracosts':
            self._save_extra_costs(first_day, last_day, post_data)
        if allocate_type == 'dynamicextracosts':
            self._save_dynamic_extra_costs(first_day, last_day, post_data)
        if allocate_type == 'teamcosts':
            self._save_team_costs(first_day, last_day, post_data)
        return Response({"status": True})
