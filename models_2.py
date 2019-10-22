from django.db import models
from django.contrib.sites.models import Site
from django.forms.models import model_to_dict


class Country(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='Страна')
    name_to = models.CharField(max_length=100, verbose_name='В какую страну?', help_text='Падеж', blank=True, null=True)
    name_where = models.CharField(max_length=100, verbose_name='В какой стране?', help_text='Падеж', blank=True,
                                  null=True)
    code = models.IntegerField(blank=True, null=True)
    translit = models.CharField(max_length=100, default='', db_index=True)

    def __str__(self):
        return self.name

    def get_to(self):
        return self.name_to or self.name

    @property
    def to_dict(self):
        return model_to_dict(self, fields=['id', 'name', 'code'])

    class Meta:
        verbose_name = 'Страна'
        verbose_name_plural = 'Страны'


class CityOutSatellite(models.Model):
    from_cityout = models.ForeignKey('CityOut', on_delete=models.CASCADE, related_name='satellite_city')
    to_cityout = models.ForeignKey('CityOut', on_delete=models.CASCADE, related_name='main_city')
    manual = models.BooleanField(u'Установлен вручную?', default=False)
    ignore = models.BooleanField(u'Игнорировать сателлит', default=False)
    distance = models.PositiveSmallIntegerField(u'Расстояние, км', default=0)
    is_satellite = models.BooleanField(u'Это сателлит?', default=True, blank=True)


class CityOut(models.Model):
    name = models.CharField(max_length=100, verbose_name='Город вылета')
    name_from = models.CharField(max_length=100, verbose_name='Из какого города?', help_text='Падеж',
                                 blank=True, null=True)
    code = models.IntegerField(blank=True, null=True)
    translit = models.CharField(max_length=100, default='', db_index=True)
    satellites = models.ManyToManyField('self', symmetrical=False, through=CityOutSatellite)
    latitude = models.DecimalField(u'Широта', max_digits=10, decimal_places=7, default=0)
    longitude = models.DecimalField(u'Широта', max_digits=10, decimal_places=7, default=0)
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, blank=True, null=True, verbose_name='Поддомен для города')
    smm_freq = models.IntegerField(default=1, verbose_name='Частота упоминаний в СММ, дни')

    def __str__(self):
        return self.name

    @property
    def coordinate(self):
        return (self.latitude, self.longitude,)

    def get_from(self):
        return self.name_from or 'г. %s' % self.name

    @property
    def to_dict(self):
        return model_to_dict(self, fields=['id', 'name', 'code'])

    class Meta:
        verbose_name = 'Город вылета'
        verbose_name_plural = 'Города вылета'


class SmmPhotos(models.Model):
    name = models.CharField(max_length=200, verbose_name='Название фото')
    country = models.ForeignKey(Country, on_delete=models.CASCADE, blank=True, null=True)


class SmmLog(models.Model):
    city_out = models.ForeignKey(CityOut, on_delete=models.CASCADE, verbose_name='Город вылета')
    country = models.ForeignKey(Country, on_delete=models.CASCADE, blank=True, null=True)
    pub_date = models.DateTimeField(blank=True, null=True, verbose_name='Дата Публикации')
    photo = models.ForeignKey(SmmPhotos, on_delete=models.CASCADE)
    gradient = models.BooleanField(u'Цвет градиента ч/б', default=False, blank=True)


class CityIn(models.Model):
    name = models.CharField(max_length=100, verbose_name='Курорт')
    name_to = models.CharField(max_length=100, verbose_name='В какой курорт?', help_text='Падеж', blank=True, null=True)
    name_where = models.CharField(max_length=100, verbose_name='В какой?', help_text='Падеж', blank=True,
                                  null=True)
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    translit = models.CharField(max_length=100, default='', db_index=True)
    is_checked = models.BooleanField(u'Проверена ли корректность?', default=False, blank=True)

    def __str__(self):
        return self.name

    def get_to(self):
        return self.name_to or self.name

    @property
    def to_dict(self):
        return model_to_dict(self, fields=['id', 'name'])

    class Meta:
        verbose_name = 'Курорт'
        verbose_name_plural = 'Курорты'


class CityInArea(models.Model):
    city_in = models.ForeignKey(CityIn, on_delete=models.CASCADE, verbose_name='Курорт')
    name = models.CharField(max_length=200, verbose_name='Район курорта')
    full_name = models.CharField(max_length=300, verbose_name='Полное название курорта')
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    is_actual = models.BooleanField(u'Актуален?', default=False, blank=True)

    class Meta:
        unique_together = ('city_in', 'name', 'country', 'full_name')


class Tours(models.Model):
    city_out = models.ForeignKey(CityOut, on_delete=models.CASCADE, verbose_name='Город вылета')
    city_in = models.ForeignKey(CityIn, on_delete=models.CASCADE, verbose_name='Курорт')
    tour_date = models.DateField(blank=True, null=True, verbose_name='Дата')
    scan_date = models.DateField(blank=True, null=True)
    min_price = models.IntegerField(blank=True, null=True, verbose_name='Цена от')
    nights = models.IntegerField(blank=True, null=True, verbose_name='Ночей')
    tickets_dpt = models.NullBooleanField(default=False, blank=True, null=True)
    tickets_rtn = models.NullBooleanField(default=False, blank=True, null=True)
    all_inclusive = models.NullBooleanField(default=False, verbose_name='Все включено?')
    need_del = models.NullBooleanField(default=False, verbose_name='Используется при парсинге для чистки БД')


class Hotels(models.Model):
    hotel = models.CharField(max_length=200, verbose_name='Отель')
    stars =  models.CharField(max_length=10, verbose_name='Количество звезд')
    rating = models.FloatField(null=True, blank=True, default=None)
    city_in = models.ForeignKey(CityIn, on_delete=models.CASCADE, verbose_name='Курорт')
    is_actual = models.BooleanField(u'Актуален отель?', default=False, blank=True)

    def __str__(self):
        return self.hotel

    class Meta:
        unique_together = ('hotel', 'stars', 'city_in')
        verbose_name = 'Отель'
        verbose_name_plural = 'Отели'


class Rooms(models.Model):
    room = models.CharField(max_length=200, verbose_name='Вид номера')
    room_rus = models.CharField(max_length=200, verbose_name='Вид номера (рус)')
    place = models.CharField(max_length=200, verbose_name='Размещение')
    is_actual = models.BooleanField(u'Актуален?', default=False, blank=True)

    def __str__(self):
        return self.room_rus

    class Meta:
        unique_together = ('room', 'room_rus', 'place')
        verbose_name = 'Номер'
        verbose_name_plural = 'Номера'


class TourName(models.Model):
    name = models.CharField(max_length=400, verbose_name='Название тура')
    is_actual = models.BooleanField(u'Актуален?', default=False, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Название тура'
        verbose_name_plural = 'Названия туров'


class Meal(models.Model):
    meal = models.CharField(max_length=50, verbose_name='Тип питания')
    description = models.TextField(verbose_name='Питание')
    all_unclusive = models.NullBooleanField(default=False, verbose_name='Все включено?')

    def __str__(self):
        return '%s %s' % (self.meal, self.description)

    class Meta:
        verbose_name = verbose_name_plural = 'Питание'


class TourOperator(models.Model):
    name = models.CharField('Тур оператор', max_length=250, unique=True)


class ToursFullData(models.Model):
    city_out = models.ForeignKey(CityOut, on_delete=models.CASCADE, verbose_name='Город вылета')
    city_in = models.ForeignKey(CityIn, on_delete=models.CASCADE, verbose_name='Курорт')
    area  = models.ForeignKey(CityInArea, on_delete=models.CASCADE, verbose_name='Район курорта', blank=True, null=True)
    tour_date = models.DateField(blank=True, null=True, verbose_name='Дата', db_index=True)
    scan_date = models.DateField(blank=True, null=True, db_index=True)
    price = models.IntegerField(blank=True, null=True, verbose_name='Цена')
    nights = models.IntegerField(blank=True, null=True, verbose_name='Количество ночей', db_index=True)
    tickets_dpt = models.NullBooleanField(default=False, blank=True, null=True)
    tickets_rtn = models.NullBooleanField(default=False, blank=True, null=True)
    hotel = models.ForeignKey(Hotels, on_delete=models.CASCADE, verbose_name='Отель')
    room = models.ForeignKey(Rooms, on_delete=models.CASCADE, verbose_name='Номер')
    meal = models.ForeignKey(Meal, on_delete=models.CASCADE, verbose_name='Питание')
    tour = models.ForeignKey(TourName, on_delete=models.CASCADE, verbose_name='Название тура')
    all_inclusive = models.NullBooleanField(default=False, verbose_name='Все включено?')
    need_del = models.NullBooleanField(default=False, verbose_name='Используется при парсинге для чистки БД')
    tour_operator = models.ForeignKey(TourOperator, on_delete=models.CASCADE, verbose_name='Тур оператор', blank=True, null=True, default=None)


class ScanLog(models.Model):
    city_out = models.ForeignKey(CityOut, on_delete=models.CASCADE)
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    scan_date = models.DateTimeField(blank=True, null=True)
    parse_dept = models.IntegerField('Глубина парсинга, дней',default=45)


class MetaTag(models.Model):
    name = models.CharField('Навзание урла', max_length=50, help_text='Служебное поле', unique=True)
    title = models.TextField('Title')
    keywords = models.TextField('Keywords')
    description = models.TextField('Description')
    h1 = models.TextField('H1')

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = verbose_name_plural = u'Мета-информация'


class Office(models.Model):
    city = models.ForeignKey(CityOut, on_delete=models.CASCADE)
    street = models.CharField(max_length=400, verbose_name='Адрес')
    office_info = models.CharField(max_length=1000, verbose_name='Примечание к адресу', blank=True, null=True)
    phone1 = models.CharField(max_length=20, verbose_name='Телефон1')
    phone2 = models.CharField(max_length=20, verbose_name='Телефон2', blank=True, null=True)
    work_time = models.CharField(max_length=1000, verbose_name='Время работы')
    sort = models.IntegerField(verbose_name='Порядок вывода', default=0)
    default = models.BooleanField(verbose_name='По умолчанию для незаполненных городов', default=False)


