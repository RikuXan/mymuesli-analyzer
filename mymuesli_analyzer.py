import requests
from os import path, makedirs, stat
from bs4 import BeautifulSoup
import json
from collections.abc import MutableMapping
from itertools import groupby
import plotly.graph_objects as go
import plotly.subplots as psp
import pandas as pd

MYMUESLI_ANALYZER_BASE_URL = 'https://www.mymuesli.com'
MYMUESLI_ANALYZER_LOCAL_CACHE_PATH = f"{path.expanduser('~')}/.cache/mymuesli-analyzer"
MYMUESLI_ANALYZER_API_HEADERS = {'mm-api-key': '69f50eca-8fb2-4cef-9871-fc13c024d903'}


class MymuesliEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (Ingredient, IngredientDict, Offer, ReadyMix)):
            return obj.__dict__

        return json.JSONEncoder.default(self, obj)


class Ingredient(object):
    ingredient_type_map = {h3.text: h3.find_parent('ul').find_previous('h2').text
                           for h3 in BeautifulSoup(requests.get(f"{MYMUESLI_ANALYZER_BASE_URL}/ingredients").text, 'html.parser').select_one('#content').select('li > div > h3')}

    @classmethod
    def from_dict(cls, dict_data):
        return cls(**dict_data)

    @classmethod
    def from_web(cls, ingredient_id):
        ingredient_page = BeautifulSoup(requests.get(f"{MYMUESLI_ANALYZER_BASE_URL}/ingredient/{ingredient_id}").text, 'html.parser')
        return cls(ingredient_id=ingredient_id,
                   name=(ingredient_name := ingredient_page.select_one('#content').select_one('h3').text),
                   subtitle=ingredient_page.select_one('#content').select_one('.subtitle').text if ingredient_page.select_one('#content').select_one('.subtitle') is not None else None,
                   ingredient_type=Ingredient.ingredient_type_map[ingredient_name] if ingredient_name in Ingredient.ingredient_type_map else 'Unbekannt',
                   hints=[span.text for span in ingredient_page.select_one('#content').select_one('.ingredient-hints').select('span')] if ingredient_page.select_one('#content').select_one('.ingredient-hints') is not None else [],
                   description=ingredient_page.select_one('#content').select_one('.description').text if ingredient_page.select_one('#content').select_one('.description') is not None else None,
                   sub_ingredients=[sub_ingredient.strip('* \t\n') for sub_ingredient in ingredient_page.select_one('#content').select_one('.subingredients').text[9:].split(', ')])

    def __init__(self, ingredient_id, name, subtitle, ingredient_type, hints, description, sub_ingredients):
        self.ingredient_id = ingredient_id
        self.name = name
        self.subtitle = subtitle
        self.ingredient_type = ingredient_type
        self.hints = hints
        self.description = description
        self.sub_ingredients = sub_ingredients

    def __repr__(self):
        return f"{self.name}"


class IngredientDict(MutableMapping):
    store = dict()

    ingredient_cache_path = f"{MYMUESLI_ANALYZER_LOCAL_CACHE_PATH}/ingredients"
    if not path.exists(ingredient_cache_path):
        makedirs(ingredient_cache_path)

    def __init__(self, *args, **kwargs):
        self.store = IngredientDict.store
        self.update(dict(*args, **kwargs))  # use the free update to set keys

    def __getitem__(self, ingredient_id):
        ingredient_cache_file_path = f"{self.__class__.ingredient_cache_path}/{ingredient_id}.json"

        if path.exists(ingredient_cache_file_path) and stat(ingredient_cache_file_path).st_size > 0:
            if ingredient_id in self.store:
                return self.store[ingredient_id]

            with open(ingredient_cache_file_path, 'r') as ingredient_cache_infile:
                self.store[ingredient_id] = json.load(ingredient_cache_infile, object_hook=Ingredient.from_dict)
        else:
            if ingredient_id in self.store:
                return self.store[ingredient_id]
            else:
                self.store[ingredient_id] = Ingredient.from_web(ingredient_id)

            with open(ingredient_cache_file_path, 'w') as ingredient_cache_outfile:
                json.dump(self.store[ingredient_id].__dict__, ingredient_cache_outfile, cls=MymuesliEncoder)

        return self.store[ingredient_id]

    def __setitem__(self, key, value):
        self.store[key] = value

    def __delitem__(self, key):
        del self.store[key]

    def __iter__(self):
        return iter(self.store)

    def __len__(self):
        return len(self.store)

    def __repr__(self):
        return self.store.__repr__()


class Offer(object):
    @classmethod
    def from_dict(cls, dict_data):
        return cls(offer_id=dict_data['id'],
                   name=dict_data['name'],
                   availability=bool(dict_data['availability']),
                   availability_for_hotspot=bool(dict_data['availableForHotspot']),
                   price=dict_data['price'],
                   original_price=float(dict_data['priceMarketing']) if dict_data['priceMarketing'] else dict_data['price'],
                   price_per_100g=float(dict_data['priceQuotation'].replace(' €/100g', '').replace(',', '.').strip()),
                   description=dict_data['description'])

    def __init__(self, offer_id, name, availability, availability_for_hotspot, price, original_price, price_per_100g, description):
        self.offer_id = offer_id
        self.name = name
        self.availability = availability
        self.availability_for_hotspot = availability_for_hotspot
        self.price = price
        self.original_price = original_price
        self.discount_percentage = (original_price - price) / original_price
        self.price_per_100g = price_per_100g
        self.description = description

    def __repr__(self):
        return f"{self.name}: {self.price:.2f} € bzw. {self.price_per_100g:.2f} €/100g ({self.discount_percentage * 100:.0f}% Rabatt)"


class ReadyMix(object):
    category_map = {
        181: 'Bircher',
        191: 'Früchte',
        201: 'Schoko',
        211: 'Sport',
        221: 'Bio',
        231: 'Balance',
        251: 'Liebe',
        261: 'Glutenfrei',
        281: 'Kinder',
        351: 'Paleo & Nüsse',
        421: 'Summer',
        451: 'Ostern',
        2031: 'Vegan',
        2111: 'DIE EISKÖNIGIN 2'
    }

    @classmethod
    def from_dict(cls, dict_data):
        return cls(**dict_data)

    def __init__(self, product_dict, search_dict, offer_dicts):
        self.name = product_dict['name']
        self.url = f"{MYMUESLI_ANALYZER_BASE_URL}{product_dict['url']}"
        self.category = product_dict['category']
        self.product_type = product_dict['type']
        self.ingredients = sorted([{
            'ingredient': IngredientDict()[ingredient['id']],
            'amount': ingredient['amount'],
            'grams': int(ingredient['amountMilligram'] / 1000)
        } for ingredient in product_dict['ingredients']], key=lambda ingredient: ingredient['grams'], reverse=True)
        self.ingredient_type_distribution = {g[0]: sum(i['grams'] for i in g[1]) / sum(i['grams'] for i in self.ingredients)
                                             for g in groupby(sorted(self.ingredients, key=lambda i: i['ingredient'].ingredient_type), key=lambda i: i['ingredient'].ingredient_type)}
        self.nutrition = product_dict['nutrition']
        self.flavour = product_dict['flavour']
        self.grams = product_dict['weight']
        self.offers = sorted([Offer.from_dict(od) for od in offer_dicts], key=lambda offer: offer.price)
        self.single_offer = next(filter(lambda o: f"{self.grams}g" in o.name, self.offers), None)
        self.likes = product_dict['likes']
        self.popularity = search_dict['popularity']
        self.filters = [list(search_dict['filter'].values())]

    def __repr__(self):
        price_string = f"{self.single_offer.price:.2f} € ({self.single_offer.price_per_100g:.2f} €/100g, -{self.single_offer.discount_percentage * 100:.0f}%) " \
            if self.single_offer is not None else f"Ausverkauft"
        return f"{self.name} @ {price_string} für {self.grams}g ({', '.join([str(ingredient['grams']) + 'g ' + ingredient['ingredient'].name for ingredient in self.ingredients])})"


class ReadyMixList(object):
    all_elements = []

    @classmethod
    def get_all_ready_mixes(cls):
        mymuesli_products = requests.get(f"{MYMUESLI_ANALYZER_BASE_URL}/api/products", headers=MYMUESLI_ANALYZER_API_HEADERS).json()
        mymuesli_search = requests.get(f"{MYMUESLI_ANALYZER_BASE_URL}/api/search", headers=MYMUESLI_ANALYZER_API_HEADERS).json()
        mymuesli_offers = requests.get(f"{MYMUESLI_ANALYZER_BASE_URL}/api/offers", headers=MYMUESLI_ANALYZER_API_HEADERS).json()

        ready_mix_search_items = filter(lambda sr: sr['type'] == 'product' and sr['brand']['key'] == 'mymuesli' and 'is-ready-mix' in sr['filter'], mymuesli_search)

        for rmsi in ready_mix_search_items:
            ReadyMixList.all_elements.append(ReadyMix(product_dict=(rmpd := next(filter(lambda product: product['id'] == rmsi['id'], mymuesli_products))),
                                                      search_dict=rmsi,
                                                      offer_dicts=list(filter(lambda offer: offer['productArticleNumber'] == rmpd['articleNumber'], mymuesli_offers))))

    def __new__(cls):
        if len(cls.all_elements) == 0:
            cls.get_all_ready_mixes()

        return cls.all_elements


if __name__ == '__main__':
    rms = ReadyMixList()
    df = pd.DataFrame({
        **{
            'Ready Mix Name': [rm.name for rm in rms],
            'Popularity': [rm.popularity for rm in rms]
        }, **{
            it: [rm.ingredient_type_distribution[it] if it in rm.ingredient_type_distribution else 0.0 for rm in rms]
            for it in set(Ingredient.ingredient_type_map.values()) | {'Unbekannt'}
        }
    }).sort_values('Popularity').head(10)

    # labels = ['1st', '2nd', '3rd', '4th', '5th']
    fig = psp.make_subplots(cols=5,
                            rows=2,
                            subplot_titles=df['Ready Mix Name'].tolist(),
                            specs=[[{'type': 'domain'}] * 5] * 2)

    for idx, (rowidx, row) in enumerate(df.iterrows()):
        fig.add_trace(
            go.Pie(labels=(col_names := list(df.head())[2:]),
                   values=[row[col_name] for col_name in col_names],
                   name=row['Ready Mix Name']),
            col=(idx % 5) + 1,
            row=int(idx / 5) + 1)

    # fig.add_trace(go.Pie(labels=labels, values=[38, 27, 18, 10, 7], name='Starry Night',
    #                      marker_colors=night_colors), 1, 1)
    # fig.add_trace(go.Pie(labels=labels, values=[28, 26, 21, 15, 10], name='Sunflowers',
    #                      marker_colors=sunflowers_colors), 1, 2)
    # fig.add_trace(go.Pie(labels=labels, values=[38, 19, 16, 14, 13], name='Irises',
    #                      marker_colors=irises_colors), 2, 1)
    # fig.add_trace(go.Pie(labels=labels, values=[31, 24, 19, 18, 8], name='The Night Café',
    #                      marker_colors=cafe_colors), 2, 2)

    fig.update_layout(showlegend=False,
                      annotations=[{
                          'text': row['Ready Mix Name'],
                          'x': (1 / 6) * (int(idx % 5) + 1),
                          'y': -0.1 + 0.5 * (int(idx / 5) + 1),
                          'font_size': 20,
                          'showarrow': False
                      } for idx, (rowidx, row) in enumerate(df.iterrows())])

    fig.show()
    pass
