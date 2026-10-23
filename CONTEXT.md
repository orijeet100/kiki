# Kiki

A voice assistant that keeps the household grocery list and gets it ready for the next grocery order.

## Language

### The list

**List**:
The one household grocery list: every Frequent Item, plus the Occasional Items that are Needed.
_Avoid_: weekly list, shopping list, cart

**Item**:
A thing the household buys, such as chicken or walnuts. It stays on the List between Orders.
_Avoid_: product, entry

**Buying pattern**:
How often the household buys an Item: Frequent or Occasional.
_Avoid_: kind, type, category, frequency

**Frequent**:
An Item bought often. It always stays on the List, and is Needed again once an Order is complete.
_Avoid_: constant, staple, regular, weekly

**Occasional**:
An Item bought now and then. It is on the List only while Needed, and becomes Not needed once an Order is complete. An Item the household stopped buying is simply Occasional.
_Avoid_: non-constant, one-off, extra, this time, archived, deleted

**Needed**:
The status of an Item that goes in the next Order.
_Avoid_: pending, present, wanted

**Not needed**:
The status of an Item left out of the next Order, until it is asked for again. A Frequent Item stays visible on the List with this label.
_Avoid_: NTT, skipped, paused, removed, deleted

**Usual quantity**:
How many of an Item a normal Order has, such as 3 tomatoes or 1 chicken. It can be changed for one Order without changing the usual.
_Avoid_: default amount, count

### Ordering

**Store**:
Where an Order is placed. Today that is Wegmans, through Instacart.
_Avoid_: vendor, source, shop

**Product**:
The exact thing the Store sells, with the Store's own id, such as "Wegmans Grade AA Large Eggs, 18 Count". An Item has at most one Product, the one the Cart gets for it; "eggs" is the Item, the 18-count carton is its Product.
_Avoid_: SKU, variant, link, item (for this)

**Cart**:
The Store's basket that Kiki fills from the Needed Items. The household checks it out; Kiki never does.
_Avoid_: basket, order (for this), list

**Order**:
One grocery purchase placed at a Store, and the record of which Items it got. It is complete once it is known which Items came; that, not the calendar, starts the List over.
_Avoid_: purchase, delivery, cart

**Order line**:
One Product in an Order: the Product that was placed (never what came instead), how many, and whether it was found, substituted or missing.
_Avoid_: order item, row

**Reset**:
Starting the List over by hand: every Frequent Item Needed at its Usual quantity, every Occasional Item Not needed. Until Orders complete themselves, the household does this when the groceries have come.
_Avoid_: clear (that makes everything Not needed), new order

**Missing**:
An Item that was Needed but did not come in the Order. It stays Needed for the next Order.
_Avoid_: unavailable, failed, out of stock

**Substitute**:
An Item picked in the Store because the wanted one was unavailable. It is a one-off and Kiki does not remember it.
_Avoid_: swap, replacement
