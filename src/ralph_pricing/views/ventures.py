# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import datetime

from django.utils.translation import ugettext_lazy as _

from ralph_pricing.views.reports import Report, currency
from ralph_pricing.models import UsageType, ExtraCostType, Venture
from ralph_pricing.forms import DateRangeForm


class AllVentures(Report):
    '''
        Reports for all ventures
    '''
    template_name = 'ralph_pricing/ventures_all.html'
    Form = DateRangeForm
    section = 'all-ventures'
    report_name = _('All Ventures Report')

    @staticmethod
    def _get_visible_usage_types():
        return UsageType.objects.exclude(show_in_report=False).order_by('name')

    @staticmethod
    def get_data(
        warehouse,
        start,
        end,
        show_in_ralph=False,
        forecast=False,
        **kwargs
    ):
        '''
            Generate raport for all ventures

            :param integer warehouse: Id warehouse for which is generate report
            :param datetime start: Start of the time interval
            :param datetime end: End of the time interval
            :param boolean show_in_ralph: if true, show only active ventures
            :param boolean forecast: if true, generate forecast raport
            :returns list: List of lists with report data and percent progress
            :rtype list:
        '''
        # 'show_in_ralph' == 'show only active' checkbox in gui
        ventures = Venture.objects.order_by('name')
        total_count = ventures.count() + 1  # additional step for post-process
        data = []
        totals = {}
        values = []
        for i, venture in enumerate(ventures):
            if show_in_ralph and not venture.is_active:
                continue

            values_row = {}
            values.append(values_row)
            count, price, cost = venture.get_assets_count_price_cost(
                start, end,
            )
            path = '/'.join(
                v.name for v in venture.get_ancestors(include_self=True),
            )
            row = [
                venture.venture_id,
                path,
                venture.is_active,
                venture.department,
                venture.business_segment,
                venture.profit_center,
                count,
                currency(price),
                currency(cost),
            ]
            column = len(row)
            for usage_type in AllVentures._get_visible_usage_types():
                count, price = venture.get_usages_count_price(
                    start,
                    end,
                    usage_type,
                    warehouse.id if usage_type.by_warehouse else None,
                    forecast=forecast,
                )
                row.append(count)
                column += 1
                if usage_type.show_value_percentage:
                    row.append('')
                    totals[column] = totals.get(column, 0) + count
                    values_row[column] = count
                    column += 1
                if price is None:
                    row.append('NO PRICE')
                else:
                    row.append(currency(price))
                column += 1
                if usage_type.show_price_percentage:
                    row.append('')
                    totals[column] = totals.get(column, 0) + count
                    values_row[column] = price
                    column += 1
            for extra_cost_type in ExtraCostType.objects.order_by('name'):
                row.append(currency(venture.get_extra_costs(
                    start,
                    end,
                    extra_cost_type,
                )))
            progress = (100 * i) // total_count
            data.append(row)
            yield min(progress, 99), data
        for row, values_row in zip(data, values):
            for column, total in totals.iteritems():
                if total:
                    row[column] = '{:.2f}%'.format(
                        100 * values_row[column] / total,
                    )
        yield 100, data

    @staticmethod
    def get_header(**kwargs):
        header = [
            _("ID"),
            _("Venture"),
            _("Active at %s" % datetime.date.today()),
            _("Department"),
            _("Business segment"),
            _("Profit center"),
            _("Assets count"),
            _("Assets price"),
            _("Assets cost"),
        ]
        for usage_type in AllVentures._get_visible_usage_types():
            header.append(_("{} count").format(usage_type.name))
            if usage_type.show_value_percentage:
                header.append(_("{} count %").format(usage_type.name))
            header.append(_("{} price").format(usage_type.name))
            if usage_type.show_price_percentage:
                header.append(_("{} price %").format(usage_type.name))
        for extra_cost_type in ExtraCostType.objects.order_by('name'):
            header.append(extra_cost_type.name)
        return header
