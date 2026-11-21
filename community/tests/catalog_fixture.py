"""Assign only synthetic test catalogs to the replacement fixture namespace."""
from copy import deepcopy


def remaining_fixture(manifest):
    value = deepcopy(manifest)
    value['r2Prefix'] = 'catalog/official-remaining-v1/offline-fixture'
    for shard in value['shards']:
        shard['key'] = value['r2Prefix'] + '/' + shard['file']
    return value
