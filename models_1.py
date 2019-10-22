from random import shuffle

from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.core.validators import MinValueValidator
from django.db import models
from model_utils.managers import InheritanceQuerySet
from smart_selects.db_fields import ChainedForeignKey

from apps.adverts_extras.models import City, Street, District, Metro
from apps.adverts_generator_v2.models import PhraseGroupSet
from apps.adverts_v2.forms import modelform_fabric
from libs.stdimage import StdImageField, ACTION_CROP
from libs.utils import import_by_name
from . import options

__all__ = ('Category', 'CategoryParsingSettings', 'Advert', 'ApartmentAdvert', 'AdvertPhoto', 'AdvertInWork',
           'CottageAdvert')


class Category(models.Model):
    title = models.CharField(verbose_name='Название', max_length=100, unique=True)
    alias = models.SlugField(verbose_name='ЧПУ')

    model_name = models.CharField(verbose_name='Имя модели', max_length=100, default='advert')
    builder_class_name = models.CharField(verbose_name='Класс билдела', max_length=100, default='CommonBuilder')

    class Meta:
        verbose_name = 'категория'
        verbose_name_plural = 'категории'

    def __str__(self):
        return self.title

    def get_model(self):
        return apps.get_model(self._meta.app_label, self.model_name)

    def get_change_form_class(self):
        return modelform_fabric(model=self.get_model())

    def get_archive_builder_class(self):
        return import_by_name(name=self.builder_class_name, module=options.ARCHIVE_BUILDERS_MODULE)

    def get_adverts_queryset(self):
        return Advert.objects.get_category_queryset(category_alias=self.alias).order_by('created')


class CategoryParsingSettings(models.Model):
    category = models.ForeignKey(Category, verbose_name='Категория')
    city = models.ForeignKey(City, verbose_name='Город', null=True, blank=True)

    price_from = models.PositiveIntegerField(verbose_name='Цена от', default=0)
    price_to = models.PositiveIntegerField(verbose_name='Цена до', default=0)
    price_step = models.PositiveIntegerField(verbose_name='Шаг цены', default=1, validators=[MinValueValidator(1)])

    parser_name = models.CharField(verbose_name='Имя парсера', max_length=100)
    parser_url = models.TextField(verbose_name='Ссылка')
    parser_pages_limit = models.PositiveSmallIntegerField(verbose_name='Количество страниц', default=5)

    is_active = models.BooleanField(verbose_name='Активность', default=True)

    class Meta:
        verbose_name = 'настройка парсинга для категории'
        verbose_name_plural = 'настройки парсинга для категорий'

    def __str__(self):
        return 'Настройки парсинга для категории {}'.format(self.category.title)


class AdvertsQueryset(InheritanceQuerySet):
    def visible(self, value=True):
        return self.filter(visible=bool(value))

    def available(self):
        return self.visible().filter(advertinwork=None)

    def get_new_adverts(self):
        return self.available().filter(status=options.NEW)

    def get_rejected_adverts(self):
        return self.available().filter(status=options.REJECTED)

    def get_used_adverts(self):
        return self.available().filter(status=options.USED)

    def get_adverts_in_work(self, user):
        return self.visible().filter(advertinwork__user=user)

    def get_by_status(self, user, status):
        if status == options.IN_WORK:
            return self.get_adverts_in_work(user)
        return self.available().filter(status=status)


class AdvertsManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_subclasses()

    def get_category_queryset(self, category_alias):
        return self.get_queryset().filter(category__alias=category_alias)


class Advert(models.Model):
    category = models.ForeignKey(Category, verbose_name='Категория')
    status = models.PositiveIntegerField(verbose_name='Статус', choices=options.ADVERT_STATUSES, default=options.NEW)

    city = models.ForeignKey(City, verbose_name='Город', blank=True, null=True)
    district = ChainedForeignKey(District, verbose_name='Район', chained_field='city', chained_model_field='city',
                                 auto_choose=True, blank=True, null=True)
    metro = ChainedForeignKey(Metro, verbose_name='Метро', chained_field='city', chained_model_field='city',
                              auto_choose=True, blank=True, null=True)

    title = models.TextField(verbose_name='Заголовок', blank=True)
    title_original = models.TextField(verbose_name='оригинальный заголовок', blank=True)
    description = models.TextField(verbose_name='Описание', blank=True)
    description_original = models.TextField(verbose_name='Оригинальное описание', blank=True)
    price = models.PositiveIntegerField(verbose_name='Цена', null=True, blank=True)

    visible = models.BooleanField(verbose_name='Видимость', default=True)

    donor = models.PositiveSmallIntegerField(verbose_name='Донор', choices=options.DONORS)
    donor_url = models.URLField(verbose_name='Урл объявления', unique=True)

    created = models.DateTimeField(verbose_name='Дата добавления', auto_now_add=True)
    updated = models.DateTimeField(verbose_name='Дата изменения', auto_now=True)

    objects = AdvertsManager.from_queryset(AdvertsQueryset)()

    class Meta:
        verbose_name = 'объявление'
        verbose_name_plural = 'объявления'
        ordering = ('-created', )

    def __str__(self):
        return 'Объявление #{0} в категории {1}'.format(self.id, self.category.title)

    def save(self, *args, **kwargs):
        self.generate_texts(overwrite=False)
        super().save(*args, **kwargs)

    def get_change_form_class(self):
        return self.category.get_change_form_class()

    @property
    def short_stats_items_generator(self):
        if self.price:
            yield 'Цена', '{0} руб.'.format(self.price)

    @property
    def short_stats(self):
        return list(self.short_stats_items_generator)[:options.ADVERT_DETALIZATION_ITEMS_LIMIT]

    @property
    def days_count_all(self):
        from django.utils import timezone
        now = timezone.now()
        return (now - self.created).days

    def generate_texts(self, fields=None, overwrite=True):
        for field_name in fields or options.AUTO_GENERATED_FIELDS:
            try:
                self._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue

            if not overwrite and getattr(self, field_name):
                continue

            new_text = self.generate_text(field_name, exists_check=False)
            setattr(self, field_name, new_text)

    def generate_text(self, field_name, exists_check=True):
        if field_name not in options.AUTO_GENERATED_FIELDS:
            raise ValueError('Field {} is not enabled for text generation'.format(field_name))

        # проверка на наличие поля
        if exists_check:
            self._meta.get_field(field_name)

        groupset = PhraseGroupSet.objects.filter(category=self.category, advert_field=field_name).order_by('?').first()
        return groupset.generate_text_from_object(self) if groupset else ''

    def can_edit(self, user):
        if not self.visible:
            return False, 'Объявление не активно.'

        try:
            in_work = self.advertinwork
        except AdvertInWork.DoesNotExist:
            pass
        else:
            if in_work.user != user:
                return False, 'Объявление находится в работе у пользователя {0}'.format(in_work.user)

        return True, None


class AdvertPhoto(models.Model):
    advert = models.ForeignKey(Advert, verbose_name='Объявление', related_name='photos')
    image = StdImageField(verbose_name='Фото', upload_to=options.ADVERTS_PHOTOS_PATH, crop_area=False,
                          variations={
                              'small': dict(
                                  size=options.ADVERTS_PHOTOS_SMALL_SIZE,
                                  action=ACTION_CROP,
                              ),
                              'admin_thumbnail': dict(alias_for='small'),
                          })
    checksum = models.CharField(verbose_name='Контрольная сумма', max_length=100, unique=True)
    enabled = models.BooleanField(verbose_name='Активна', default=True)
    is_main = models.BooleanField(verbose_name='Главная', default=False)

    class Meta:
        verbose_name = 'фото к объявлению'
        verbose_name_plural = 'фото к объявлениям'

    def __str__(self):
        return 'Фото к объявлению {0}'.format(self.advert)

    def can_edit(self, user):
        return self.advert.can_edit(user)


class AdvertInWork(models.Model):
    advert = models.OneToOneField(Advert, verbose_name='Объявление')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Пользователь', related_name='adverts_in_work')

    class Meta:
        verbose_name = 'объявление в работе'
        verbose_name_plural = 'объявления в работе'

    def __str__(self):
        return '{0} в работе у пользователя {1}'.format(self.advert, self.user)


class ApartmentAdvert(Advert):
    street = ChainedForeignKey(Street, verbose_name='Улица', chained_field='district', chained_model_field='district',
                               auto_choose=True, blank=True, null=True)
    house_number = models.CharField(verbose_name='Номер дома', max_length=30, blank=True)

    house_material = models.PositiveSmallIntegerField(verbose_name='Материал дома', choices=options.HOUSE_MATERIALS,
                                                      null=True, blank=True)
    rooms_number = models.PositiveSmallIntegerField(verbose_name='Количество комнат', null=True, blank=True)
    floor = models.PositiveSmallIntegerField(verbose_name='Этаж', null=True, blank=True)
    floors_total = models.PositiveSmallIntegerField(verbose_name='Этажей в доме', null=True, blank=True)
    area_living = models.PositiveSmallIntegerField(verbose_name='Жилая площадь', null=True, blank=True)
    area_total = models.PositiveSmallIntegerField(verbose_name='Общая площадь', null=True, blank=True)
    area_kitchen = models.PositiveSmallIntegerField(verbose_name='Площадь кухни', null=True, blank=True)
    ceiling_height = models.FloatField(verbose_name='Высота потолков', null=True, blank=True)
    beds_number = models.PositiveSmallIntegerField(verbose_name='Количество спальных мест', null=True, blank=True)

    condition = models.PositiveSmallIntegerField(verbose_name='Состояние', choices=options.CONDITIONS_CHOICES,
                                                 blank=True, null=True)
    apartment_type = models.PositiveSmallIntegerField(verbose_name='Тип квартиры',
                                                      choices=options.APARTMENT_TYPES_CHOICES, blank=True, null=True)

    has_furniture = models.BooleanField(verbose_name='С мебелью', default=False)
    has_kitchen = models.BooleanField(verbose_name='С кухней', default=False)
    has_refrigerator = models.BooleanField(verbose_name='С холодильником', default=False)
    has_washing_machine = models.BooleanField(verbose_name='С посудомоечной машиной', default=False)
    has_conditioner = models.BooleanField(verbose_name='С кондиционером', default=False)
    has_tv = models.BooleanField(verbose_name='С телевизором', default=False)
    has_internet = models.BooleanField(verbose_name='С интернетом', default=False)

    class Meta:
        verbose_name = 'объявление о сдаче квартиры'
        verbose_name_plural = 'объявления в сдаче квартир'

    def save(self, *args, **kwargs):
        if not self.title:
            self.title = self.address
        super().save(*args, **kwargs)

    @property
    def apartment_type_value(self):
        return self.get_apartment_type_display()

    @property
    def condition_value(self):
        return self.get_condition_display()

    @property
    def comfort_list(self):
        return ', '.join(attr for attr in self.get_available_comfort_attributes())

    @property
    def comfort_list_shuffled(self):
        comfort_list = list(self.get_available_comfort_attributes())
        shuffle(comfort_list)
        return ', '.join(comfort_list)

    @property
    def days_count(self):
        from django.utils import timezone
        now = timezone.now()
        return (now - self.created).days

    def get_available_comfort_attributes(self):
        if self.has_furniture:
            yield 'мебель'
        if self.has_kitchen:
            yield 'кухня'
        if self.has_refrigerator:
            yield 'холодильник'
        if self.has_washing_machine:
            yield 'посудомоечная машина'
        if self.has_conditioner:
            yield 'кондиционер'
        if self.has_tv:
            yield 'телевизор'
        if self.has_internet:
            yield 'интернет'

    @property
    def short_stats_items_generator(self):
        yield from super().short_stats_items_generator

        if self.rooms_number:
            yield 'Количество комнат', self.rooms_number

        if self.floor:
            yield 'Этаж', '{0}/{1}'.format(self.floor, self.floors_total) if self.floors_total else self.floor

        if self.area_living:
            yield 'Жилая площадь', '{} кв. м'.format(self.area_living)

        if self.area_total:
            yield 'Общая площадь', '{} кв. м'.format(self.area_total)

        if self.area_kitchen:
            yield 'Площадь кухни', '{} кв. м'.format(self.area_kitchen)

        if self.beds_number:
            yield 'Спальных мест', self.beds_number

        if self.condition:
            yield 'Состояние', self.get_condition_display()

        if self.apartment_type:
            yield 'Тип квартиры', self.get_apartment_type_display()

        for attr in self.get_available_comfort_attributes():
            yield attr.capitalize(), 'да'

        if self.created:
            yield 'Счётчик жизни объявления', '{} дн.'.format(self.days_count)

    @property
    def address(self):
        address = ''
        if self.city:
            address += 'г. {}'.format(self.city.title)
            if self.district:
                address += ', {} р-н'.format(self.district.title)
                if self.street:
                    address += ', {}'.format(self.street.title)
                    if self.house_number:
                        address += ' {}'.format(self.house_number)
        return address


class CottageAdvert(Advert):
    area_house = models.PositiveSmallIntegerField(verbose_name='Площадь дома', null=True, blank=True)
    area_land = models.PositiveSmallIntegerField(verbose_name='Площадь участка', null=True, blank=True)
    wall_material = models.PositiveSmallIntegerField(verbose_name='Материал стен', choices=options.WALL_MATERIALS,
                                                     null=True, blank=True)
    number_floors = models.PositiveSmallIntegerField(verbose_name='Кол-во этажей', null=True, blank=True)

    class Meta:
        verbose_name = 'объявление о продаже коттеджа'
        verbose_name_plural = 'объявления о продаже коттеджей'

    def save(self, *args, **kwargs):
        # if not self.title:
        #     self.title = self.address
        super().save(*args, **kwargs)

    @property
    def wall_material_value(self):
        return self.get_wall_material_display()

    @property
    def short_stats_items_generator(self):
        if self.price:
            yield 'Цена', '{0} руб.'.format(self.price)

    def short_stats_items_generator(self):
        yield from super().short_stats_items_generator

        if self.area_house:
            yield 'Площадь дома', '{} кв. м'.format(self.area_house)

        if self.area_land:
            yield 'Площадь участка', '{} соток'.format(self.area_land)

        if self.wall_material:
            yield 'Материал стен',  self.get_wall_material_display()

        if self.number_floors:
            yield 'Кол-во этажей', self.number_floors