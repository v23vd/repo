import json
import locale
import sys
import calendar
from itertools import chain
from time import strptime
from datetime import date, timedelta, datetime
from collections import Iterable

from django.db.models import Q, Max, Count, Min
from django.db.models.functions import Lower, TruncMonth
from django.http import HttpResponsePermanentRedirect, JsonResponse, Http404
from django.http import HttpResponseRedirect
from django.core.serializers.json import DjangoJSONEncoder
from django.urls import reverse, resolve
from django.views.generic import ListView
from django.views.generic.base import RedirectView
from django.template import engines
from django.contrib.sites.models import Site
from django.contrib.sites.shortcuts import get_current_site

from django_tables2 import RequestConfig
from django_select2.views import AutoResponseView
from dateutil.relativedelta import relativedelta
from pytils.dt import ru_strftime, MONTH_NAMES

from .forms import FindForm, FindHotelForm
from .models import Tours, CityIn, CityOut, ToursFullData, Country, MetaTag, Office, CityOutSatellite, Rooms, Meal,\
    CityInArea, TourName
from .models import Hotels as HotelReference

from .tables import ToursTable, HotelsTable


class Countering:
    count = 0

    def reset(self):
        Countering.count = 0
        return ''

    def increment(self):
        self.count += 1
        Countering.count += 1
        return ''

    def decrement(self):
        self.count -= 1
        return ''


def hotel_reference(request):
    """
    Выборка отелей по странам или регионам для динамической подгрузки на дополнительный фильтр по отелям
    :param request:
    :return:
    """
    hotels = []
    if request.GET.get('region'):
        hotels = list(HotelReference.objects.filter(city_in__id__in=request.GET.get('region', []).split(','),
                                                    is_actual=True).values('id', 'hotel'))
    elif request.GET.get('country'):
        hotels = list(HotelReference.objects.filter(city_in__id__in=request.GET.get('country', []).split(','),
                                                    is_actual=True).values('id', 'hotel'))
    return JsonResponse(hotels, safe=False)


def rooms_reference(request):
    """
    Выборка типов комнат по отелям, курортам или странам для динамической подгрузки на дополнительный фильтр по отелям
    :param request:
    :return:
    """
    rooms = []
    if request.GET.get('hotel'):
        rooms = list(Rooms.objects.filter(is_actual=True,
                                          toursfulldata__hotel__id__in=request.GET.get('hotel', []).split(','))
                     .distinct().values('id', 'room'))
    elif request.GET.get('region'):
        rooms = list(Rooms.objects.filter(is_actual=True,
                                          toursfulldata__city_in__id__in=request.GET.get('region', []).split(',')
                                          ).distinct().values('id', 'room'))
    elif request.GET.get('country'):
        rooms = list(HotelReference.objects.filter(is_actual=True,
                                                   toursfulldata__city_in__country__id__in=
                                                   request.GET.get('country', []).split(',')).distinct()
                     .values('id', 'room'))
    return JsonResponse(rooms, safe=False)


def area_reference(request):
    """
    Выборка типов районов по курортам или странам для динамической подгрузки на дополнительный фильтр по отелям
    :param request:
    :return:
    """
    areas = []
    if request.GET.get('region'):
        areas = list(CityInArea.objects.filter(city_in__id__in=request.GET.get('region', []).split(','))
                     .distinct().values('id', 'name'))
    elif request.GET.get('country'):
        areas = list(HotelReference.objects.filter(country__id__in=request.GET.get('country', []).split(',')).distinct()
                     .values('id', 'room'))
    return JsonResponse(areas, safe=False)


def tour_name_reference(request):
    """
    Выборка названия туров по курортам или странам для динамической подгрузки на дополнительный фильтр по отелям
    :param request:
    :return:
    """
    tour_names = []
    if request.GET.get('region'):
        tour_names = list(TourName.objects.filter(toursfulldata__city_in__id__in=
                                                  request.GET.get('region', []).split(',')).distinct()
                          .values('id', 'name'))
    elif request.GET.get('country'):
        tour_names = list(TourName.objects.filter(toursfulldata__city_in__country__id__in=
                                                  request.GET.get('country', []).split(',')).distinct()
                     .values('id', 'room'))
    return JsonResponse(tour_names, safe=False)


def stars_reference(request):
    """
    Выборка названия звезд по курортам или странам для динамической подгрузки на дополнительный фильтр по отелям
    :param request:
    :return:
    """
    stars = []
    if request.GET.get('region'):
        stars = list(HotelReference.objects.filter(toursfulldata__city_in__id__in=
                                                   request.GET.get('region', []).split(',')).distinct()
                     .values('stars', 'stars').order_by('stars'))
    elif request.GET.get('country'):
        stars = list(HotelReference.objects.filter(toursfulldata__city_in__country__id__in=
                                                   request.GET.get('country', []).split(',')).distinct()
                     .values('stars', 'stars').order_by('stars'))
    return JsonResponse(stars, safe=False)


def meals_reference(request):
    """
    Выборка типов питания по курортам или странам для динамической подгрузки на дополнительный фильтр по отелям
    :param request:
    :return:
    """
    meals = []
    if request.GET.get('region'):
        meals = list(Meal.objects.filter(toursfulldata__city_in__id__in=
                                         request.GET.get('region', []).split(',')).distinct().values('id', 'meal'))
    elif request.GET.get('country'):
        meals = list(Meal.objects.filter(toursfulldata__city_in__country__id__in=request.GET.get('country', [])
                                         .split(',')).distinct().values('id', 'meal'))
    return JsonResponse(meals, safe=False)


class UtilMixin(object):
    def get_cities_out(self, **kwargs):
        city_out = kwargs.get('city_out')
        if city_out:
            cities_out_ids = CityOut.objects.filter(name__in=[city_out]).values_list('id', flat=True)
            return chain([city_out], CityOut.objects.filter(pk__in=cities_out_ids))
        else:
            return CityOut.objects.all()

    def get_satellites(self, **kwargs):
        city_out = kwargs.get('city_out')
        if city_out:
            satellites_ids = city_out.satellite_city.filter(ignore=False, is_satellite=True) \
                .values_list('to_cityout__id', flat=True)
            return chain([city_out], CityOut.objects.filter(pk__in=satellites_ids))
        else:
            return CityOut.objects.all()

    def get_countries(self, **kwargs):
        country = kwargs.get('country')
        if country:
            countries_ids = Country.objects.filter(name__in=[country]).values_list('id', flat=True)
            return chain([country], Country.objects.filter(pk__in=countries_ids))
        else:
            return Country.objects.all()

    def get_cities_in(self, **kwargs):
        city_in = kwargs.get('city_in')
        if city_in:
            cities_in_ids = CityIn.objects.filter(name__in=[city_in]).values_list('id', flat=True)
            return chain([city_in], CityIn.objects.filter(pk__in=cities_in_ids))
        else:
            return CityIn.objects.all()

    @staticmethod
    def get_tours_month_dict(**kwargs):
        """
        Формирование информации по количеству туров и минимальной цене, сгруппированной по месяцам
        :param kwargs: параметры для кверисета
        :return: возвращается словарь где ключем является дата вида "2019-04-01", а значением - словарь с этой же датой,
        стоимостью(минимальной и количеством туров)
        """
        tours_query_params = {'tickets_dpt': True,
                              'tickets_rtn': True, }
        if kwargs.get('all_inclusive'):
            tours_query_params['all_inclusive'] = True
        if kwargs.get('cities_out', '-') != '-':
            tours_query_params['city_out__translit'] = kwargs['cities_out']
        if kwargs.get('countries_in', '-') != '-':
            tours_query_params['city_in__country__translit'] = kwargs['countries_in']
        if kwargs.get('cities_in', '-') != '-':
            tours_query_params['city_in__translit'] = kwargs['cities_in']
        tours_month_data = Tours.objects.filter(**tours_query_params) \
            .annotate(month=TruncMonth('tour_date')).values('month').annotate(price=Min('min_price'), count=Count('id'))
        return {item['month'].month: item for item in tours_month_data}

    @staticmethod
    def prepare_form_initial_params(**kwargs):
        """
        Общий метод для подготовки начальных параметров поисковой формы
        :param kwargs:
        :return: возвращает словарь с данными для последующего заполнения верхней формы
        """
        form_initial = {}
        if kwargs.get('cities_out', '-') != '-':
            cities_out_qs = CityOut.objects.filter(translit__in=kwargs['cities_out'].split('+'))
            form_initial['cities_out'] = cities_out_qs
        if kwargs.get('cities_in', '-') != '-':
            cities_in_qs = CityIn.objects.filter(translit__in=kwargs['cities_in'].split('+'))
            form_initial['cities_in'] = cities_in_qs
            form_initial['countries_in'] = Country.objects.filter(cityin__in=cities_in_qs)
        if kwargs.get('to_date'):
            to_date = datetime.strptime(kwargs['to_date'], '%Y-%m-%d').date()
            form_initial['min_date'] = to_date
            form_initial['max_date'] = to_date + timedelta(days=1)
        if kwargs.get('on_date'):
            today = date.today()
            search_date = kwargs['on_date'].split('-')
            search_month_number = strptime(search_date[0], '%B').tm_mon
            num_days = calendar.monthrange(int(search_date[1]), search_month_number)
            if search_date[0] == today.strftime('%B'):
                on_date = today
            else:
                on_date = date(int(search_date[1]), search_month_number, 1)
            form_initial['min_date'] = on_date
            form_initial['max_date'] = date(int(search_date[1]), search_month_number, num_days[1])
        if kwargs.get('on_year'):
            today = date.today()
            if int(kwargs['on_year']) == today.year:
                on_year = today
            else:
                on_year = date(int(kwargs['on_year']), 1, 1)
            form_initial['min_date'] = on_year
            form_initial['max_date'] = date(int(kwargs['on_year']), 12, 31)
        return form_initial


class ToursListBase(UtilMixin, ListView):
    model = Tours
    ordering = 'min_price'
    template_name = 'base.html'

    @property
    def scan_date(self):
        qs = super().get_queryset()
        if not hasattr(self, '_scan_date'):
            self._scan_date = qs.aggregate(scan_date=Max('scan_date'))['scan_date']
        return self._scan_date

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(tickets_dpt=True, tickets_rtn=True).select_related()

    def breadcrumbs(self, **kwargs):
        breadcrumbs = []
        url = ''
        if 'cities_out' in kwargs:
            url = reverse('index')
        breadcrumbs.append(('Все туры', url))
        if 'cities_out' in kwargs:
            city_url_kwargs = {'cities_out': kwargs['cities_out']}
            if kwargs['cities_out'] == '-':
                city_out = u'всех городов'
            else:
                city_out = '%s' % CityOut.objects.filter(translit__in=kwargs['cities_out'].split('+'))[0]
            url = ''
            if 'countries_in' in kwargs:
                url = reverse('tours_city_out', kwargs=city_url_kwargs)
            breadcrumbs.append(('Туры из %s' % city_out, url))

        if 'countries_in' in kwargs:
            country_kwargs = {'cities_out': kwargs['cities_out'],
                              'countries_in': kwargs['countries_in']}
            if kwargs['countries_in'] == '-':
                country_out = u'всех стран'
            else:
                country_out = ' %s' % Country.objects.filter(translit__in=kwargs['countries_in'].split('+'))[0]
            url = ''
            if 'cities_in' in kwargs:
                url = reverse('tours_countries_in', kwargs=country_kwargs)
            breadcrumbs.append((str(country_out), url))

        if 'cities_in' in kwargs:
            if kwargs['cities_in'] == '-':
                city_in = u'Все города'
            else:
                city_in = CityIn.objects.filter(translit__in=kwargs['cities_in'].split('+'))[0]
            breadcrumbs.append((str(city_in), ''))
        return breadcrumbs

    def get_countries_info(self, **kwargs):
        params = {'city_out__in': self.get_satellites(city_out=kwargs['city_out'])}
        if not params['city_out__in']:
            del params['city_out__in']
        if 'year' in kwargs:
            params['tour_date__year'] = kwargs['year']
        if 'month' in kwargs:
            params['tour_date__month'] = kwargs['month']
        return self.get_queryset().values('city_in__country__name') \
                                  .filter(**params) \
                                  .annotate(price=Min('min_price'), count=Count('*')) \
                                  .order_by('city_in__country__name')

    def get_cities_info(self, **kwargs):
        params = {'city_out__in': self.get_satellites(city_out=kwargs['city_out'])}
        if not params['city_out__in']:
            del params['city_out__in']
        if 'country' in kwargs:
            params['city_in__country__in'] = self.get_countries(country=kwargs['country'])
        if 'city_in' in kwargs:
            params['city_in__in'] = self.get_cities_in(city_in=kwargs['city_in'])
        if 'year' in kwargs:
            params['tour_date__year'] = kwargs['year']
        if 'month' in kwargs:
            params['tour_date__month'] = kwargs['month']
        info = self.get_queryset().values('city_out__name') \
                                  .filter(**params) \
                                  .annotate(price=Min('min_price'), count=Count('*')) \
                                  .order_by('city_out__name')
        info = tuple(info)
        minimum = sys.maxsize
        for item in info:
            if minimum > item['price']:
                minimum = item['price']
        if minimum == sys.maxsize:
            minimum = None
        return {'minimum': minimum, 'cities': info}

    def get_dates_info(self, **kwargs):
        # params = {'city_out__in': self.get_satellites(city_out=kwargs['city_out'])}
        params = {'city_out__in': self.get_cities_out(city_out=kwargs['city_out'])}
        if not params['city_out__in']:
            del params['city_out__in']
        if 'country' in kwargs:
            params['city_in__country'] = kwargs['country']
        if 'city_in' in kwargs:
            params['city_in'] = kwargs['city_in']

        qs = self.get_queryset().extra(select={'month': 'MONTH(tour_date)', 'year': 'EXTRACT(YEAR FROM tour_date)'}) \
                                .filter(**params) \
                                .values('month', 'year') \
                                .annotate(price=Min('min_price'), count=Count('*')) \
                                .order_by('year', 'month')
        return qs

    def get_tours_params(self, **kwargs):
        params = {}
        if kwargs.get('countries_in'):
            country = kwargs['countries_in']
            if isinstance(country, str):
                country = [country]
            params['city_in__in'] = CityIn.objects.filter(country__in=country)

        if kwargs.get('cities_in'):
            params['city_in__in'] = kwargs['cities_in']

        if kwargs.get('min_date'):
            params['tour_date__gte'] = kwargs['min_date']

        if kwargs.get('max_date'):
            params['tour_date__lte'] = kwargs['max_date']

        params['nights__gte'] = 1
        if kwargs.get('min_nights'):
            params['nights__gte'] = kwargs['min_nights']

        if kwargs.get('max_nights'):
            params['nights__lte'] = kwargs['max_nights']

        if kwargs.get('max_price'):
            params['min_price__lte'] = kwargs['max_price']

        if kwargs.get('all_inclusive'):
            params['all_inclusive'] = kwargs['all_inclusive']

        return params

    def get_down_on_date(self, **kwargs):
        today = date.today()
        down = []
        current_locale = locale.getdefaultlocale()
        for month_num in range(12):
            next_date = today + relativedelta(months=month_num)
            try:
                locale.setlocale(locale.LC_ALL, 'en_US.utf8')  # locale
            except Exception:
                try:
                    locale.setlocale(locale.LC_ALL, 'en')
                except Exception as e:
                    print('An error setlocale: {0}'.format(e))
            en_month = next_date.strftime('%B')
            try:
                locale.setlocale(locale.LC_ALL, current_locale)  # locale
            except Exception:
                try:
                    locale.setlocale(locale.LC_ALL, 'ru')
                except Exception as e:
                    print('An error setlocale: {0}'.format(e))
            ru_month = ru_strftime('%B', next_date)  # locale
            year = next_date.year
            url = reverse('tours_by_date', kwargs={
                'cities_out': kwargs.get('cities_out', '-'),
                'cities_in': kwargs.get('cities_in', '-'),
                'on_date': '%s-%d' % (en_month, year),
                'countries_in':  kwargs.get('countries_in', '-'),
            })
            # down.append((url, '%s %d' % (ru_month, year,)))  # locale
            down.append((url, next_date))  # locale
        # locale.setlocale(locale.LC_ALL, '.'.join(current_locale))  # locale

        for add_year in range(2):
            url = reverse('tours_by_year', kwargs={
                'cities_out': kwargs.get('cities_out', '-'),
                'cities_in': kwargs.get('cities_in', '-'),
                'on_year': today.year + add_year,
                'countries_in':  kwargs.get('countries_in', '-'),
            })
            down.append((url, today.year + add_year))

        return down

    def redirect_by_form_data(self, form_data):
        cities_out = form_data.pop('cities_out') if 'cities_out' in form_data else []
        cities_out = '+'.join(c.translit for c in cities_out) if cities_out else '-'

        countries_in = form_data.pop('countries_in') if 'countries_in' in form_data else []
        countries_in = '+'.join(c.translit for c in countries_in) if countries_in else '-'

        cities_in = form_data.pop('cities_in') if 'cities_in' in form_data else []
        cities_in = '+'.join(c.translit for c in cities_in) if cities_in else '-'
        alerts = form_data.pop('alerts', None)
        self.request.session['alerts'] = alerts if alerts else []

        if form_data:
            self.request.session['saved_params'] = json.dumps(form_data, cls=DjangoJSONEncoder)

        if cities_in != '-':
            kwargs = {'cities_out': cities_out,
                      'countries_in': countries_in,
                      'cities_in': cities_in}
            return reverse('tours_cities_in', kwargs=kwargs)
        elif countries_in != '-':
            kwargs = {'cities_out': cities_out,
                      'countries_in': countries_in,}
            return reverse('tours_countries_in', kwargs=kwargs)
        elif cities_out != '-':
            return reverse('tours_city_out', kwargs={'cities_out': cities_out,})
        else:
            return None

    def get_satellit_link(self, **kwargs):
        satellites = self.get_satellites(**kwargs)
        url_name = 'tours_city_out'
        if 'cities_in' in kwargs:
            url_name = 'tours_cities_in'
        elif 'countries_in' in kwargs:
            url_name = 'tours_countries_in'
        params = {k: v for k, v in kwargs.items() if k in ('cities_out', 'countries_in', 'cities_in')}
        if satellites:
            params.update({'cities_out': '+'.join(c.translit for c in satellites), })
            return reverse(url_name, kwargs=params)

    def get_satellits(self, **kwargs):
        satellites = self.get_satellites(**kwargs)
        params = {k: v for k, v in kwargs.items() if k in ('cities_out', 'countries_in', 'cities_in')}
        url_name = 'tours_city_out'
        if 'on_year' in kwargs:
            url_name = 'tours_by_year'
            params["on_year"] = kwargs["on_year"]
        elif 'on_date' in kwargs:
            url_name = 'tours_by_date'
            on_date = kwargs["on_date"]
            en_month = on_date.strftime('%B')
            year = on_date.year
            params["on_date"] = '%s-%d' % (en_month, year)
        elif 'cities_in' in kwargs:
            url_name = 'tours_cities_in'
        elif 'countries_in' in kwargs:
            url_name = 'tours_countries_in'
        if satellites:
            for satellit in satellites:
                params.update({'cities_out': satellit.translit, })
                yield (reverse(url_name, kwargs=params), satellit)

    def get_countires_links(self, **params):
        countries_qs = self.get_queryset().filter(**self.get_tours_params(**params)) \
                                          .values_list('city_in__country__name', 'city_in__country__translit')
        if params.get('cities_out', '-') != '-':
            countries_qs = countries_qs.filter(city_out__translit__in=params['cities_out'].split('+'))
        for name, translit in set(countries_qs.distinct()):
            url_kwargs = {'cities_out': '-', 'countries_in': translit}
            url_kwargs.update(params)
            yield (name, reverse('tours_countries_in', kwargs=url_kwargs))

    def get_all_countries(self):
        countries = Country.objects.all().order_by('-name')
        return countries

    def get_offices(self, **kwargs):
        offices_satellites = None

        offices = Office.objects.all().order_by('sort')
        if 'city_out' in kwargs:
            city_out = kwargs['city_out']
            offices_main = offices.filter(city=city_out)

            if offices_main.__len__() == 0:
                offices_main = Office.objects.filter(default__exact=True).order_by('sort')
                sattelites = CityOutSatellite.objects.filter(from_cityout=city_out).values_list("to_cityout")
                offices_satellites = offices.filter(city__in=sattelites)
        else:
            offices_main = offices

        return {"offices_main": offices_main, "offices_satellites": offices_satellites}

    def get_context_data(self, object_list=None, **kwargs):
        context = super().get_context_data(object_list=object_list, **kwargs)
        context.update(kwargs)
        context['countering'] = Countering
        context['scan_date'] = self.scan_date
        self.object_list = context['object_list']
        context['search_form_type'] = 'tours'
        tours_table = ToursTable(self.object_list, template_name='table.html')
        RequestConfig(self.request).configure(tours_table)
        context['tours_table'] = tours_table
        context['down_dates'] = self.get_down_on_date(**kwargs)
        context['satellit_link'] = self.get_satellit_link(**kwargs)
        context['satellits'] = self.get_satellits(**kwargs)
        context['countries'] = self.get_all_countries()
        context['offices'] = self.get_offices(**kwargs)
        metatag_info = MetaTag.objects.get(name=resolve(self.request.path_info).url_name)
        engine = engines['django']
        context.update({
            'title': engine.from_string(metatag_info.title).render(context, self.request),
            'description': engine.from_string(metatag_info.description).render(context, self.request),
            'keywords': engine.from_string(metatag_info.keywords).render(context, self.request),
            'h1': engine.from_string(metatag_info.h1).render(context, self.request),
        })
        return context

    def get_form_redirect(self, form_initial):
        form = FindForm(initial=form_initial)
        redirect_url = None

        # del self.request.session['sort']
        if self.request.GET.get("sort"):
            sort = self.request.GET.get("sort")
            if sort is None:
                # self.request.session['sort'] = self.ordering
                sort = "min_price"
            self.request.session['sort'] = sort
        # else:
        #     self.request.session['sort'] = self.ordering

        if 'submit' in self.request.GET:
            form = FindForm(self.request.GET)
            if form.is_valid():
                redirect_url = self.redirect_by_form_data(form.cleaned_data)
                self.object_list = self.object_list.filter(**self.get_tours_params(**form.cleaned_data))
        if self.request.session.get('saved_params'):
            data = json.loads(self.request.session.get('saved_params'))
            data.update({k: [i.pk for i in v] if isinstance(v, Iterable) and not isinstance(v, str) else v for k, v in form_initial.items()})
            form = FindForm(data=data)
            if form.is_valid():
                self.object_list = self.object_list.filter(**self.get_tours_params(**form.cleaned_data))
        return form, redirect_url

    def get_all_inclusive_search_params(self, search_model, **kwargs):
        """
        метод формирует параметры для поиска стран или курортов в блок "Все включено"
        :param search_model: Указывается для какой модели формируем список, например 'Country', 'CityOut' и т.д., для
        подстановки префикса к параметру, где это необходимо
        :param kwargs: кварги запроса
        :return: возвращается словарь с параметрами для кверисета
        """
        prefix = 'cityin__' if search_model == 'Country' else ''
        tours_query_params = {prefix+'tours__all_inclusive': True,
                              prefix+'tours__tickets_dpt': True,
                              prefix+'tours__tickets_rtn': True,}
        if kwargs.get('cities_out', '-') != '-':
            tours_query_params[prefix+'tours__city_out__translit'] = kwargs['cities_out']
        if kwargs.get('countries_in', '-') != '-':
            tours_query_params[prefix+'tours__city_in__country__translit'] = kwargs['countries_in']
        if kwargs.get('cities_in', '-') != '-':
        	tours_query_params[prefix+'tours__city_in__translit'] = kwargs['cities_in']
        if kwargs.get('on_date', '-') != '-':
            # on_date = datetime.strptime(kwargs['on_date'], '%B-%Y').date()
            tours_query_params[prefix+'tours__tour_date__month'] = kwargs['on_date'].month
            tours_query_params[prefix+'tours__tour_date__year'] = kwargs['on_date'].year
        return tours_query_params

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        city_out = None
        seconds_cities_out = None
        form_initial = {}
        if 'cities_out' in kwargs and kwargs['cities_out'] != '-':
            cities_out_qs = CityOut.objects.filter(translit__in=kwargs['cities_out'].split('+'))
            self.object_list = self.object_list.filter(city_out__in=cities_out_qs)
            form_initial['city_out'] = cities_out_qs
            city_out, *seconds_cities_out = cities_out_qs

        dates_info = {'countries_info': self.get_countries_info(city_out=city_out),
                      'cities_info': self.get_cities_info(city_out=city_out),
                      'dates_info': self.get_dates_info(city_out=city_out)}

        form, redirect_url = self.get_form_redirect(form_initial)
        if redirect_url is not None:
            return HttpResponseRedirect(redirect_url)

        context = self.get_context_data(object_list=self.queryset, **kwargs)
        context.update(dates_info)
        context['city_out'] = city_out
        context['seconds_cities_out'] = seconds_cities_out
        context['breadcrumbs'] = self.breadcrumbs(**kwargs)
        context['form'] = form
        return self.render_to_response(context)


class ToursCities(ToursListBase):

    def get_context_data(self, object_list=None, **kwargs):
        context = super().get_context_data(object_list=object_list, **kwargs)
        down_qs = CityOut.objects.filter(tours__scan_date=self.scan_date).distinct()\
            .annotate(price=Min('tours__min_price'), count=Count('tours')).order_by(Lower('name'))
        down = [(reverse('tours_city_out', args=(c.translit,)), c.name, c.price, c.count)
                for c in down_qs]

        down_unavailable_qs = CityOut.objects.exclude(pk__in=down_qs.values_list('pk', flat=True)) \
                                             .distinct() \
                                             .order_by(Lower('name'))
        down_unavailable = [
            (reverse('tours_city_out', args=(c.translit,)), c.name)
             for c in down_unavailable_qs
        ]

        # формирование данных для блока Все включено
        all_inclusive_list = []
        tours_query_params = self.get_all_inclusive_search_params('CityOut', **kwargs)
        ai_min_price_list = CityOut.objects.annotate(price=Min('tours__min_price', filter=Q(**tours_query_params)))\
            .exclude(price__isnull=True).values('name', 'translit', 'price')
        for item in ai_min_price_list:
            all_inclusive_list.append({
                'name': item['name'],
                'price': item['price'],
                'link': reverse('tours_all_inclusive', kwargs={'cities_out': item['translit'],
                                                               'countries_in': '-',
                                                               'cities_in': '-',
                                                               'on_date': '-'})
            })

        context.update({
            'down': down,
            'down_unavailable': down_unavailable,
            'countries_links': self.get_countires_links(),
            'all_inclusive': all_inclusive_list
        })
        return context

    def dispatch(self, *args, **kwargs):
        try:
            city_out = CityOut.objects.filter(site=get_current_site(self.request)).first()
        except (CityOut.DoesNotExist, Site.DoesNotExist):
            city_out = None
        if city_out:
            kwargs['cities_out'] = city_out.translit
            self.request.path_info = reverse('tours_city_out', kwargs={'cities_out': city_out.translit})
            return ToursCityOut.as_view()(self.request, **kwargs)
        return super().dispatch(*args, **kwargs)


class ToursCityOut(ToursListBase):

    def get_context_data(self, object_list=None, **kwargs):
        context = super().get_context_data(object_list=object_list, **kwargs)
        countries = Country.objects.filter(cityin__tours__city_out__translit=kwargs['cities_out']).distinct()\
            .annotate(price=Min('cityin__tours__min_price'), count=Count('cityin__tours')).order_by(Lower('name'))
        down = ((reverse('tours_countries_in', kwargs={'cities_out': kwargs['cities_out'], 'countries_in': c.translit}),
                c.name, c.price, c.count)
                for c in countries)

        down_qs = Country.objects.filter(cityin__tours__in=self.object_list).distinct() \
            .annotate(price=Min('cityin__tours__min_price'), count=Count('cityin__tours')).order_by(Lower('name'))
        down_unavailable_qs = Country.objects.exclude(pk__in=down_qs.values_list('pk', flat=True)) \
                                             .order_by(Lower('name')) \
                                             .distinct()
        down_unavailable = [
            (reverse('tours_countries_in', kwargs={'cities_out': kwargs['cities_out'], 'countries_in': c.translit}),
             c.name)
            for c in down_unavailable_qs
        ]

        # формирование данных для блока Все включено
        all_inclusive_list = []
        tours_query_params = self.get_all_inclusive_search_params('Country', **kwargs)
        ai_min_price_list = Country.objects.annotate(price=Min('cityin__tours__min_price', filter=Q(**tours_query_params)))\
            .exclude(price__isnull=True).values('name', 'translit', 'price')
        for item in ai_min_price_list:
            all_inclusive_list.append({
                'name': item['name'],
                'price': item['price'],
                'link': reverse('tours_all_inclusive', kwargs={'cities_out': kwargs['cities_out'],
                                                               'countries_in': item['translit'],
                                                               'cities_in': '-',
                                                               'on_date': '-'})
            })

        context.update({
            'down': down,
            'down_unavailable': down_unavailable,
            'countries_links': self.get_countires_links(cities_out=kwargs['cities_out']),
            'all_inclusive': all_inclusive_list,
        })
        return context

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        city_out = None
        seconds_cities_out = None
        form_initial = {}
        if kwargs['cities_out'] != '-':
            cities_out_qs = CityOut.objects.filter(translit__in=kwargs['cities_out'].split('+'))
            self.object_list = self.object_list.filter(city_out__in=cities_out_qs)
            form_initial['cities_out'] = cities_out_qs
            city_out, *seconds_cities_out = cities_out_qs

        dates_info = {'countries_info': self.get_countries_info(city_out=city_out),
                      'cities_info': self.get_cities_info(city_out=city_out),
                      'dates_info': self.get_dates_info(city_out=city_out)}

        form, redirect_url = self.get_form_redirect(form_initial)
        if redirect_url is not None:
            return HttpResponseRedirect(redirect_url)

        context = self.get_context_data(object_list=self.object_list,
                                        cities_out=kwargs['cities_out'],
                                        city_out=city_out)
        context.update(dates_info)
        context['city_out'] = city_out
        context['seconds_cities_out'] = seconds_cities_out
        context['breadcrumbs'] = self.breadcrumbs(**kwargs)
        context['form'] = form
        return self.render_to_response(context)


class ToursCountriesIn(ToursListBase):

    def get_context_data(self, object_list=None, **kwargs):
        context = super().get_context_data(object_list=object_list, **kwargs)
        cities_in = CityIn.objects.filter(tours__city_in__country__translit=kwargs['countries_in'],
                                          tours__city_out__translit=kwargs['cities_out']).distinct()\
            .annotate(price=Min('tours__min_price'), count=Count('tours')).order_by(Lower('name'))
        cities_out = kwargs['cities_out']
        down = ((reverse('tours_cities_in',
                         kwargs={'cities_out': cities_out,
                                 'countries_in': c.country.translit,
                                 'cities_in': c.translit}),
                 c.name, c.price, c.count)
                for c in cities_in)

        cities_in_qs = CityIn.objects.filter(tours__in=self.object_list).distinct() \
            .annotate(price=Min('tours__min_price'), count=Count('tours')).order_by(Lower('name'))
        down_unavailable_qs = CityIn.objects.exclude(pk__in=(c.pk for c in cities_in)) \
                                            .order_by(Lower('name')) \
                                            .distinct()

        if kwargs['countries_in'] != '-':
            down_unavailable_qs = down_unavailable_qs.filter(country__translit__in=kwargs['countries_in'].split('+'))

        down_unavailable = [
            (reverse('tours_cities_in',
                     kwargs={'cities_out': cities_out,
                             'countries_in': c.country.translit,
                             'cities_in': c.translit}),
             c.name)
            for c in down_unavailable_qs
        ]

        # формирование данных для блока Все включено
        all_inclusive_list = []
        tours_query_params = self.get_all_inclusive_search_params('CityIn', **kwargs)
        ai_min_price_list = CityIn.objects.annotate(price=Min('tours__min_price', filter=Q(**tours_query_params)))\
            .exclude(price__isnull=True).values('name', 'translit', 'price')
        for item in ai_min_price_list:
            all_inclusive_list.append({
                'name': item['name'],
                'price': item['price'],
                'link': reverse('tours_all_inclusive', kwargs={'cities_out': kwargs['cities_out'],
                                                               'countries_in': kwargs['countries_in'],
                                                               'cities_in': item['translit'],
                                                               'on_date': '-'})
            })

        context.update({
            'down': down,
            'down_unavailable': down_unavailable,
            'countries_links': self.get_countires_links(cities_out=kwargs['cities_out']),
            'all_inclusive': all_inclusive_list,
        })
        return context

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        city_out = None
        country = None
        seconds_cities_out = None
        form_initial = {}
        if kwargs['cities_out'] != '-':
            cities_out_qs = CityOut.objects.filter(translit__in=kwargs['cities_out'].split('+'))
            self.object_list = self.object_list.filter(city_out__in=cities_out_qs)
            form_initial['cities_out'] = cities_out_qs
            city_out, *seconds_cities_out = cities_out_qs
        if kwargs['countries_in'] != '-':
            countries_qs = Country.objects.filter(translit__in=kwargs['countries_in'].split('+'))
            self.object_list = self.object_list.filter(city_in__country__in=countries_qs)
            form_initial['countries_in'] = countries_qs
            country, *seconds_countries = countries_qs

        dates_info = {'countries_info': self.get_countries_info(city_out=city_out),
                      'cities_info': self.get_cities_info(city_out=city_out, country=country),
                      'dates_info': self.get_dates_info(city_out=city_out, country=country)}

        form, redirect_url = self.get_form_redirect(form_initial)
        if redirect_url is not None:
            return HttpResponseRedirect(redirect_url)

        context = self.get_context_data(object_list=self.object_list,
                                        city_out=city_out,
                                        country=country,
                                        **kwargs)
        context.update(dates_info)
        context['city_out'] = city_out
        context['seconds_cities_out'] = seconds_cities_out
        context['breadcrumbs'] = self.breadcrumbs(**kwargs)
        context['form'] = form
        return self.render_to_response(context)
