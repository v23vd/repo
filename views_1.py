import os
import uuid

from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.core.urlresolvers import reverse
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from apps.adverts_v2.forms import CountForm
from apps.adverts_v2.models import Category, Advert, AdvertPhoto, AdvertInWork
from libs.decorators import ajax_required
from libs.utils import ChoicesHelper, import_by_name
from . import options


def get_statuses_counts(request, category):
    statuses_counts = {}
    queryset = Advert.objects.get_category_queryset(category_alias=category.alias)
    for val, _ in options.ADVERT_STATUSES:
        if val == options.IN_WORK:
            count = queryset.visible().filter(advertinwork__user=request.user).count()
        else:
            count = queryset.available().filter(status=val).count()
        statuses_counts[val] = count
    return statuses_counts


class AdvertsList(View, TemplateResponseMixin):
    template_name = 'adverts_v2/adverts.html'
    status = None
    category = None

    def dispatch(self, request, *args, **kwargs):
        self.category = get_object_or_404(Category, alias=kwargs.pop('category'))
        return super().dispatch(request, *args, **kwargs)

    def get_adverts_queryset(self):
        return self.category.get_adverts_queryset().get_by_status(user=self.request.user, status=self.status).visible()

    def get_paginated_adverts(self):
        paginator = Paginator(self.get_adverts_queryset(), options.ADVERTS_ON_PAGE)
        paginator_page = self.request.GET.get('page', 1)
        try:
            return paginator.page(paginator_page)
        except PageNotAnInteger:
            return paginator.page(1)
        except EmptyPage:
            return paginator.page(paginator.num_pages)

    def render_adverts_list(self):
        return render_to_string('adverts_v2/adverts-list.html', {
            'paginated_adverts': self.get_paginated_adverts(),
            'statuses': options.ADVERT_STATUSES_FULL,
            'status': self.status,
            'current_category': self.category,
        })

    def get(self, request):
        context = {
            'rendered_adverts_list': self.render_adverts_list(),
        }

        if request.is_ajax():
            return JsonResponse(context)

        def build_info(value, title, extra):
            return value, title, extra, self.category.get_adverts_queryset().get_by_status(request.user, value).count()

        context.update(
            current_category=self.category,
            categories=Category.objects.all(),
            status=self.status,
            statuses=[build_info(value, title, extra) for value, title, extra in options.ADVERT_STATUSES_FULL]
        )
        return self.render_to_response(context)


class NewAdvertsList(AdvertsList):
    status = options.NEW


class RejectedAdvertsList(AdvertsList):
    status = options.REJECTED


class UsedAdvertsList(AdvertsList):
    status = options.USED


class AdvertsInWork(AdvertsList):
    status = options.IN_WORK


class AdvertChange(View, TemplateResponseMixin):
    template_name = 'adverts_v2/advert-form.html'

    @method_decorator(ajax_required)
    def dispatch(self, request, *args, **kwargs):
        advert = get_object_or_404(Advert, id=kwargs.pop('advert_id'))
        can_edit, error = advert.can_edit(request.user)
        if not can_edit:
            return JsonResponse({
                'error': 'Редактирование объявления запрещено. {0}'.format(error)
            })

        kwargs.update(advert=advert)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, advert):
        form_class = advert.get_change_form_class()
        return self.render_to_response({
            'form': form_class(instance=advert)
        })

    def post(self, request, advert):
        form_class = advert.get_change_form_class()
        form = form_class(instance=advert, data=request.POST)
        if form.is_valid():
            if not form.has_changed():
                return JsonResponse({
                    'not_changed': True
                })

            advert = form.save()
            return JsonResponse({
                'updated_advert': render_to_string('adverts_v2/advert-in-list.html', {
                    'advert': advert,
                    'status': advert.status,
                    'statuses': options.ADVERT_STATUSES_FULL,
                })
            })

        form_errors = {}
        for key, value in form.errors.items():
            form_errors.setdefault(key, []).append(value)
        print(form_errors)
        return JsonResponse({
            'form_errors': form_errors
        })


class AdvertsBulkCreate(View, TemplateResponseMixin):
    template_name = 'adverts_v2/advert-bulk-create-form.html'
    category = None
    form_class = None

    @method_decorator(ajax_required)
    def dispatch(self, request, *args, **kwargs):
        self.category = get_object_or_404(Category, alias=kwargs.pop('category'))
        self.form_class = self.category.get_change_form_class()
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return self.render_to_response({
            'form_count': CountForm(),
            'form': self.form_class()
        })

    def post(self, request):
        form_count = CountForm(request.POST)
        if not form_count.is_valid():
            form_errors = {}
            for key, value in form_count.errors.items():
                form_errors.setdefault(key, []).append(value)
            return JsonResponse({
                'form_errors': form_errors
            })

        form = self.form_class(request.POST)
        if form.is_valid():
            for _ in range(0, form_count.cleaned_data['count']):
                form._meta.model.objects.create(
                    donor=options.DUMMY,
                    donor_url=options.DUMMY_URL.format(uuid.uuid4()),
                    category=self.category,
                    **form.cleaned_data
                )

            return JsonResponse({
                    'link': reverse('adverts_v2:new-adverts', args=(self.category.alias, ))
                })

        form_errors = {}
        for key, value in form.errors.items():
            form_errors.setdefault(key, []).append(value)
        return JsonResponse({
            'form_errors': form_errors
        })


@require_GET
@ajax_required
def work_complete(request, category):
    with transaction.atomic():
        adverts = Advert.objects.get_category_queryset(category).filter(advertinwork__user=request.user)
        adverts.update(status=options.USED)
        AdvertInWork.objects.filter(advert__in=adverts).delete()
    return JsonResponse({
        'redirect': reverse('adverts_v2:new-adverts', args=(category, ))
    })


@require_GET
@ajax_required
def add_to_work(request, advert_id):
    advert = get_object_or_404(Advert, id=advert_id)
    can_edit, error = advert.can_edit(request.user)
    if not can_edit:
        return JsonResponse({
            'error': 'Не удалось добавить объявление в работу. {0}'.format(error)
        })

    AdvertInWork.objects.get_or_create(advert=advert, user=request.user)
    return JsonResponse({
        'items': get_statuses_counts(request, advert.category)
    })


@require_GET
@ajax_required
def change_photo_status(request, photo_id):
    image = get_object_or_404(AdvertPhoto, id=photo_id)
    can_edit, error = image.can_edit(request.user)
    if not can_edit:
        return JsonResponse({
            'error': 'Не удалось изменить статус фото. {0}'.format(error)
        })

    status = request.GET.get('status')
    if status and status.lower() in ('false', 'true'):
        status = True if status == 'true' else False
        if image.enabled != status:
            image.enabled = status
            image.save(update_fields=('enabled',))
    return JsonResponse({})


@require_GET
@ajax_required
def change_photo_main(request, photo_id):
    image = get_object_or_404(AdvertPhoto, id=photo_id)

    try:
        image_main = get_object_or_404(AdvertPhoto, advert_id=image.advert_id, is_main=True)
        if image_main:
            image_main.is_main = False
            image_main.save(update_fields=('is_main',))
    except:
        pass

    can_edit, error = image.can_edit(request.user)
    if not can_edit:
        return JsonResponse({
            'error': 'Не удалось изменить главное фото. {0}'.format(error)
        })

    main = request.GET.get('main')
    if main and main.lower() in ('false', 'true'):
        main = True if main == 'true' else False
        if image.is_main != main:
            image.is_main = main
            image.save(update_fields=('is_main',))
    return JsonResponse({})


@require_GET
@ajax_required
def refresh_description(request, advert_id):
    advert = get_object_or_404(Advert, id=advert_id)
    can_edit, error = advert.can_edit(request.user)
    if not can_edit:
        return JsonResponse({
            'error': 'Не удалось обновить описание. {0}'.format(error)
        })

    advert.generate_texts(fields=('description', ))
    advert.save(update_fields=('description', ))
    return JsonResponse({'text': advert.description})


@require_GET
@ajax_required
def set_original_description(request, advert_id):
    advert = get_object_or_404(Advert, id=advert_id)
    can_edit, error = advert.can_edit(request.user)
    if not can_edit:
        return JsonResponse({
            'error': 'Не удалось обновить объявление. {0}'.format(error)
        })

    target_field = request.GET.get('field')
    if target_field not in options.AUTO_GENERATED_FIELDS:
        return JsonResponse({
            'error': 'Некорректное поле {}'.format(target_field)
        })

    setattr(advert, target_field, getattr(advert, '{}_original'.format(target_field)))
    advert.save(update_fields=(target_field, ))

    return JsonResponse({
        'updated_advert': render_to_string('adverts_v2/advert-in-list.html', {
            'advert': advert,
            'status': advert.status,
            'statuses': options.ADVERT_STATUSES_FULL,
        })
    })


@require_GET
@ajax_required
def change_advert_status(request, advert_id):
    advert = get_object_or_404(Advert, id=advert_id)
    can_edit, error = advert.can_edit(request.user)
    if not can_edit:
        return JsonResponse({
            'error': 'Не удалось сменить статус объявления. {0}'.format(error)
        })

    status = request.GET.get('status')
    try:
        status = int(status)
    except (TypeError, ValueError):
        return JsonResponse({
            'error': 'Не удалось изменить статус объявления. Получено некорректное значение "{0}"'.format(status)
        })

    if status not in [value for value, title in options.ADVERT_STATUSES]:
        return JsonResponse({
            'error': 'Не удалось изменить статус объявления. Получено некорректное значение "{0}"'.format(status)
        })

    if advert.status != status:
        advert.status = status
        advert.save(update_fields=('status', ))
        if status == options.IN_WORK:
            AdvertInWork.objects.get_or_create(advert=advert, user=request.user)
        else:
            AdvertInWork.objects.filter(advert=advert).delete()

    return JsonResponse({
        'items': get_statuses_counts(request, advert.category)
    })


def get_package(request, category):
    category = get_object_or_404(Category, alias=category)
    adverts_in_work = category.get_adverts_queryset().filter(advertinwork__user=request.user)
    if not adverts_in_work.exists():
        return HttpResponse('Нет объявлений в работе.')

    builder_class = category.get_archive_builder_class()
    if builder_class is None:
        return HttpResponse('Ошибка: не удалось найти сборщик архива.')

    with builder_class(adverts_in_work) as builder:
        response = HttpResponse(content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename={0}'.format(os.path.basename(builder.archive_path))

        with open(builder.archive_path, 'rb') as archive_file:
            response.write(archive_file.read())

    return response
