from collections import Mapping
from enum import Enum, auto
from functools import reduce

from .structures import ClassReference, Field, Structure
from .fields import Array, FunctionCall, Set, StructureReference

from typedpy.structures import SERIALIZATION_MAPPER


def _deep_get(dictionary, deep_key):
    keys = deep_key.split(".")
    return reduce(lambda d, key: d.get(key) if d else None, keys, dictionary)


def _set_base_mapper_no_op(cls, for_serialization):
    mapper = {}
    for k, f in cls.get_all_fields_by_name().items():
        if isinstance(f, ClassReference):
            val = aggregate_serialization_mappers(f._ty) if for_serialization else aggregate_deserialization_mappers(f._ty)
            mapper[f"{k}._mapper"] = val
        elif isinstance(f, (Array, Set)):
            items = [f.items] if isinstance(f.items, Field) else f.items if isinstance(f.items, list) else []
            values = {}
            for i in items:
                if isinstance(i, ClassReference):
                    val = aggregate_serialization_mappers(
                        i._ty) if for_serialization else aggregate_deserialization_mappers(i._ty)
                    values.update(val)
                elif isinstance(i, StructureReference):
                    val = aggregate_serialization_mappers(
                        i._newclass) if for_serialization else aggregate_deserialization_mappers(
                        i._newclass)
                    values.update(val)
            if values:
                mapper[f"{k}._mapper"] = values

        elif isinstance(f, StructureReference):
            val = aggregate_serialization_mappers(f._newclass) if for_serialization else aggregate_deserialization_mappers(
                f._newclass)
            mapper[f"{k}._mapper"] = val
        mapper[k] = k

    return mapper


def _convert_to_camelcase(key):
    words = key.split("_")
    return words[0] + "".join(w.title() for w in words[1:])


def _convert_to_snakecase(key):
    return "".join(
        ["_" + char.lower() if char.isupper() else char for char in key]
    ).lstrip("_")


def _apply_mapper(latest_mapper, key, previous_mapper, for_serialization, is_self=False):
    val = key if is_self else previous_mapper[key]
    if latest_mapper == mappers.TO_CAMELCASE:
        return _convert_to_camelcase(val)
    if latest_mapper == mappers.TO_LOWERCASE:
        return val.upper()
    latest_mapper_val = latest_mapper.get(val, val)
    if isinstance(latest_mapper_val, (FunctionCall,)):
        args = (
            [(_deep_get(previous_mapper, k) or k) for k in latest_mapper_val.args]
            if latest_mapper_val.args
            else [previous_mapper.get(key)]
        )
        if for_serialization and previous_mapper.get(key) != key:
            raise NotImplementedError("Combining functions and other mapping in a serialization mapper is unsupported")
        return FunctionCall(func=latest_mapper_val.func, args=args)
    return latest_mapper.get(val, val)


def add_mapper_to_aggregation(latest_mapper, previous_mapper, for_serialization=False):
    result_mapper = {}  # copy.deepcopy(previous_mapper)
    if not isinstance(latest_mapper, (Mapping, mappers)):
        raise TypeError("Mapper must be a mapping")
    for k, v in previous_mapper.items():
        if isinstance(v, str):
            result_mapper[k] = _apply_mapper(latest_mapper, k, previous_mapper, for_serialization=for_serialization)
        elif isinstance(v, dict):
            if not k.endswith("._mapper"):
                raise ValueError("Invalid mapper. To map nested values, use the format <key>._mapper: {...}")
            field_name = k[0: -8]
            mapped_key = field_name if for_serialization else _apply_mapper(latest_mapper,field_name, previous_mapper, for_serialization, is_self=True)

            sub_mapper = (latest_mapper.get(f"{mapped_key}._mapper", latest_mapper.get(f"{field_name}._mapper"))
                          if not isinstance(latest_mapper, mappers)
                          else latest_mapper
                          )
            if sub_mapper:
                result_mapper[f"{mapped_key}._mapper"] = (
                    add_mapper_to_aggregation(sub_mapper, v, for_serialization=for_serialization)
                )
            else:
                result_mapper[f"{mapped_key}._mapper"] = v
        elif isinstance(v, FunctionCall):
            args = v.args or [k]
            mapped_args = args if for_serialization else [
                _apply_mapper(latest_mapper, a, previous_mapper, for_serialization=for_serialization, is_self=(a==k))
                for a in args]
            if isinstance(latest_mapper, Mapping) and isinstance(latest_mapper.get(k), FunctionCall):
                raise NotImplementedError("Combining multiple functions in serialization is unsupported")
            result_mapper[k] = FunctionCall(func=v.func, args=mapped_args)

    return result_mapper


class mappers(Enum):
    TO_LOWERCASE = auto()
    TO_CAMELCASE = auto()


def get_mapper(val: Structure):
    return getattr(val.__class__, SERIALIZATION_MAPPER, {})


def aggregate_deserialization_mappers(cls, override_mapper=None, camel_case_convert=False):
    base_mapper = _set_base_mapper_no_op(cls, for_serialization=False)
    aggregate_mapper = base_mapper
    override_mapper = (override_mapper if isinstance(override_mapper, list)
                       else [override_mapper] if override_mapper else None)
    mappers_list = override_mapper if override_mapper else cls.get_aggregated_deserialization_mapper()
    for m in mappers_list:
        aggregate_mapper = add_mapper_to_aggregation(m, aggregate_mapper)
    if camel_case_convert:
        aggregate_mapper = add_mapper_to_aggregation(mappers.TO_CAMELCASE, aggregate_mapper)
    return aggregate_mapper


def aggregate_serialization_mappers(cls, override_mapper=None, camel_case_convert=False):
    base_mapper = _set_base_mapper_no_op(cls, for_serialization=True)
    aggregate_mapper = base_mapper
    override_mapper = (override_mapper if isinstance(override_mapper, list)
                       else [override_mapper] if override_mapper else None)
    mappers_list = override_mapper if override_mapper else cls.get_aggregated_serialization_mapper()
    for m in mappers_list:
        aggregate_mapper = add_mapper_to_aggregation(m, aggregate_mapper, True)
    if camel_case_convert:
        aggregate_mapper = add_mapper_to_aggregation(mappers.TO_CAMELCASE, aggregate_mapper, True)
    return aggregate_mapper
