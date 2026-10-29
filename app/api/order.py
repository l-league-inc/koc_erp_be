def order_tolist(order):
    if order == "":
        return []

    return list(map(int, order.strip(",").split(",")))


def order_tostr(order_list):
    return ",".join(map(str, order_list))


def order_append(order, id):
    if order == "":
        return f"{id}"

    return order + f",{id}"


def order_pop(order, id):
    order_list = order_tolist(order)
    if int(id) in order_list:
        order_list.remove(int(id))
    order_str = order_tostr(order_list)
    return order_str
