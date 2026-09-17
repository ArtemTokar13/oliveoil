def address_fields_from_post(post):
    return {
        "full_name": post.get("full_name", "").strip(),
        "phone": post.get("phone", "").strip(),
        "street_address": post.get("street_address", "").strip(),
        "apartment": post.get("apartment", "").strip(),
        "postal_code": post.get("postal_code", "").strip(),
        "city": post.get("city", "").strip(),
        "province": post.get("province", "").strip(),
        "is_default": post.get("is_default") == "on",
    }


def address_to_dict(address):
    """Same shape as address_fields_from_post, for a saved Address instance."""
    return {
        "full_name": address.full_name,
        "phone": address.phone,
        "street_address": address.street_address,
        "apartment": address.apartment,
        "postal_code": address.postal_code,
        "city": address.city,
        "province": address.province,
    }


def validate_address(fields):
    errors = {}
    required = {
        "full_name": "Introduce el nombre del destinatario.",
        "phone": "Introduce un teléfono de contacto.",
        "street_address": "Introduce la dirección.",
        "postal_code": "Introduce el código postal.",
        "city": "Introduce la ciudad.",
        "province": "Introduce la provincia.",
    }
    for field, message in required.items():
        if not fields.get(field):
            errors[field] = message
    if fields.get("postal_code") and not fields["postal_code"].isdigit():
        errors["postal_code"] = "El código postal solo debe contener números."
    return errors
