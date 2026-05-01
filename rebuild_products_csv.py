"""
Bygg om "Produkter 01_05_2026.csv":
- Behold artikkel-ID-ene
- Fjern master/variant-rader (ID som er prefix for andre ID-er, samt deres varianter)
- REST* -> restaurant-sortiment
- Resten -> bakeri-sortiment
- Skriv tilbake alle felt slik at det blir gyldige varer
"""
from __future__ import annotations
import csv
from pathlib import Path

SRC = Path("Produkter 01_05_2026.csv")
DST = Path("Produkter 01_05_2026_ny.csv")

# Bakeri-sortiment (navn, varegruppe_id, varegruppe_navn, mva, nettopris)
BAKERI = [
    ("Grovbrød 750g", "100", "Brød", 15, 49.00),
    ("Kneippbrød 750g", "100", "Brød", 15, 45.00),
    ("Loff 600g", "100", "Brød", 15, 42.00),
    ("Rugbrød 1kg", "100", "Brød", 15, 59.00),
    ("Speltbrød 750g", "100", "Brød", 15, 55.00),
    ("Surdeigsbrød 800g", "100", "Brød", 15, 65.00),
    ("Bondebrød 1kg", "100", "Brød", 15, 62.00),
    ("Fullkornsbrød 750g", "100", "Brød", 15, 52.00),
    ("Solsikkebrød 750g", "100", "Brød", 15, 56.00),
    ("Havrebrød 750g", "100", "Brød", 15, 54.00),
    ("Baguette 250g", "110", "Småbrød", 15, 28.00),
    ("Ciabatta 200g", "110", "Småbrød", 15, 26.00),
    ("Rundstykke grovt", "110", "Småbrød", 15, 14.00),
    ("Rundstykke fint", "110", "Småbrød", 15, 13.00),
    ("Hornbrød", "110", "Småbrød", 15, 18.00),
    ("Frokostbolle", "110", "Småbrød", 15, 16.00),
    ("Pølsebrød 6-pk", "110", "Småbrød", 15, 39.00),
    ("Hamburgerbrød 6-pk", "110", "Småbrød", 15, 45.00),
    ("Kanelbolle", "200", "Kaker og bakverk", 25, 32.00),
    ("Skolebolle", "200", "Kaker og bakverk", 25, 35.00),
    ("Solskinnsbolle", "200", "Kaker og bakverk", 25, 33.00),
    ("Wienerbrød", "200", "Kaker og bakverk", 25, 39.00),
    ("Croissant", "200", "Kaker og bakverk", 25, 35.00),
    ("Pain au chocolat", "200", "Kaker og bakverk", 25, 42.00),
    ("Sjokoladekake stk", "200", "Kaker og bakverk", 25, 49.00),
    ("Gulrotkake stk", "200", "Kaker og bakverk", 25, 49.00),
    ("Ostekake stk", "200", "Kaker og bakverk", 25, 55.00),
    ("Bringebærterte", "200", "Kaker og bakverk", 25, 59.00),
    ("Suksessterte stk", "200", "Kaker og bakverk", 25, 55.00),
    ("Verdens beste stk", "200", "Kaker og bakverk", 25, 49.00),
    ("Napoleonskake", "200", "Kaker og bakverk", 25, 45.00),
    ("Berlinerbolle", "200", "Kaker og bakverk", 25, 35.00),
    ("Smultring", "200", "Kaker og bakverk", 25, 25.00),
    ("Vaffelplate 4-pk", "200", "Kaker og bakverk", 25, 39.00),
    ("Lefse rømmebrød", "210", "Lefser og flatbrød", 15, 35.00),
    ("Tynnlefse 4-pk", "210", "Lefser og flatbrød", 15, 49.00),
    ("Potetlefse 4-pk", "210", "Lefser og flatbrød", 15, 45.00),
    ("Flatbrød 200g", "210", "Lefser og flatbrød", 15, 39.00),
    ("Knekkebrød rug", "210", "Lefser og flatbrød", 15, 42.00),
    ("Pizzabunn 30cm", "120", "Pizza og pai", 15, 35.00),
    ("Focaccia 400g", "120", "Pizza og pai", 15, 65.00),
    ("Quiche lorraine", "120", "Pizza og pai", 15, 89.00),
    ("Spinatpai", "120", "Pizza og pai", 15, 85.00),
    ("Sjokoladekake hel 1kg", "220", "Hele kaker", 25, 295.00),
    ("Marsipankake 8 pers", "220", "Hele kaker", 25, 395.00),
    ("Bløtkake jordbær 8 pers", "220", "Hele kaker", 25, 395.00),
    ("Kvæfjordkake 8 pers", "220", "Hele kaker", 25, 425.00),
    ("Sjokolademousse hel", "220", "Hele kaker", 25, 350.00),
    ("Eplekake hel", "220", "Hele kaker", 25, 275.00),
    ("Bringebærpai hel", "220", "Hele kaker", 25, 295.00),
    ("Karamellpudding stk", "230", "Dessert", 25, 49.00),
    ("Ris a la Malta porsjon", "230", "Dessert", 25, 45.00),
    ("Sjokoladepudding stk", "230", "Dessert", 25, 45.00),
    ("Tiramisu porsjon", "230", "Dessert", 25, 59.00),
    ("Panna cotta", "230", "Dessert", 25, 55.00),
    ("Kaffe latte", "300", "Drikke", 25, 49.00),
    ("Cappuccino", "300", "Drikke", 25, 45.00),
    ("Espresso", "300", "Drikke", 25, 32.00),
    ("Americano", "300", "Drikke", 25, 39.00),
    ("Filterkaffe", "300", "Drikke", 25, 32.00),
    ("Te diverse", "300", "Drikke", 25, 32.00),
    ("Kakao varm", "300", "Drikke", 25, 45.00),
    ("Iste sitron 0,5L", "300", "Drikke", 25, 39.00),
    ("Smoothie bær 0,4L", "300", "Drikke", 25, 65.00),
    ("Juice appelsin 0,4L", "300", "Drikke", 25, 49.00),
    ("Eple juice 0,33L", "300", "Drikke", 25, 35.00),
    ("Mineralvann 0,5L", "300", "Drikke", 25, 35.00),
    ("Farris 0,5L", "300", "Drikke", 25, 39.00),
    ("Coca-Cola 0,5L", "300", "Drikke", 25, 39.00),
    ("Pepsi Max 0,5L", "300", "Drikke", 25, 39.00),
    ("Solo 0,5L", "300", "Drikke", 25, 39.00),
    ("Melk 0,33L", "300", "Drikke", 15, 25.00),
    ("Yoghurt naturell 150g", "310", "Meieri", 15, 22.00),
    ("Kefir 250ml", "310", "Meieri", 15, 28.00),
    ("Cottage cheese 250g", "310", "Meieri", 15, 39.00),
    ("Smør 250g", "310", "Meieri", 15, 49.00),
    ("Bakerost 200g", "310", "Meieri", 15, 65.00),
    ("Eple Aroma 1kg", "320", "Frukt og bær", 15, 49.00),
    ("Banan 1kg", "320", "Frukt og bær", 15, 35.00),
    ("Jordbær 250g", "320", "Frukt og bær", 15, 65.00),
    ("Bringebær 125g", "320", "Frukt og bær", 15, 55.00),
    ("Smørbrød reker", "400", "Smørbrød og lunsj", 15, 95.00),
    ("Smørbrød roastbeef", "400", "Smørbrød og lunsj", 15, 89.00),
    ("Smørbrød skinke/ost", "400", "Smørbrød og lunsj", 15, 75.00),
    ("Bagel laks", "400", "Smørbrød og lunsj", 15, 95.00),
    ("Wrap kylling", "400", "Smørbrød og lunsj", 15, 89.00),
    ("Wrap vegetar", "400", "Smørbrød og lunsj", 15, 79.00),
    ("Salat caesar", "400", "Smørbrød og lunsj", 15, 119.00),
    ("Salat reker", "400", "Smørbrød og lunsj", 15, 129.00),
    ("Suppe dagens", "400", "Smørbrød og lunsj", 15, 95.00),
    ("Lapper 6-pk", "200", "Kaker og bakverk", 25, 45.00),
    ("Wienerstang", "200", "Kaker og bakverk", 25, 39.00),
    ("Linser kjeks 4-pk", "200", "Kaker og bakverk", 25, 49.00),
    ("Sjokoladekjeks 200g", "200", "Kaker og bakverk", 25, 55.00),
    ("Havrekjeks 200g", "200", "Kaker og bakverk", 25, 49.00),
    ("Pepperkaker 250g", "200", "Kaker og bakverk", 25, 65.00),
    ("Krumkaker 200g", "200", "Kaker og bakverk", 25, 89.00),
    ("Sandkaker 200g", "200", "Kaker og bakverk", 25, 75.00),
    ("Berlinerkrans 200g", "200", "Kaker og bakverk", 25, 79.00),
    ("Smultring sukker stk", "200", "Kaker og bakverk", 25, 22.00),
    ("Eplerull stk", "200", "Kaker og bakverk", 25, 35.00),
    ("Studentbrød stk", "200", "Kaker og bakverk", 25, 32.00),
    ("Hveteboller 6-pk", "110", "Småbrød", 15, 49.00),
    ("Rosinboller 6-pk", "110", "Småbrød", 15, 55.00),
    ("Tebrød 4-pk", "110", "Småbrød", 15, 39.00),
    ("Brioche stk", "110", "Småbrød", 15, 28.00),
    ("Polarbrød 6-pk", "110", "Småbrød", 15, 49.00),
    ("Fattigmann 200g", "200", "Kaker og bakverk", 25, 95.00),
    ("Goro 200g", "200", "Kaker og bakverk", 25, 95.00),
    ("Serinakaker 200g", "200", "Kaker og bakverk", 25, 79.00),
    ("Kransekake stang", "220", "Hele kaker", 25, 195.00),
    ("Bløtkake sjokolade 8 pers", "220", "Hele kaker", 25, 395.00),
    ("Marengs 200g", "200", "Kaker og bakverk", 25, 65.00),
    ("Macarons 6-pk", "200", "Kaker og bakverk", 25, 95.00),
    ("Eclair stk", "200", "Kaker og bakverk", 25, 39.00),
    ("Profiterole stk", "200", "Kaker og bakverk", 25, 35.00),
    ("Cupcake vanilje", "200", "Kaker og bakverk", 25, 39.00),
    ("Cupcake sjokolade", "200", "Kaker og bakverk", 25, 39.00),
    ("Muffins blåbær", "200", "Kaker og bakverk", 25, 35.00),
    ("Muffins sjokolade", "200", "Kaker og bakverk", 25, 35.00),
    ("Brownies stk", "200", "Kaker og bakverk", 25, 42.00),
    ("Sjokoladetrøffel 4-pk", "200", "Kaker og bakverk", 25, 65.00),
    ("Karamellbiter 200g", "200", "Kaker og bakverk", 25, 75.00),
    ("Marsipangris 100g", "200", "Kaker og bakverk", 25, 65.00),
    ("Honning 500g", "330", "Pålegg og tilbehør", 15, 95.00),
    ("Syltetøy jordbær 400g", "330", "Pålegg og tilbehør", 15, 65.00),
    ("Syltetøy bringebær 400g", "330", "Pålegg og tilbehør", 15, 65.00),
    ("Syltetøy multebær 200g", "330", "Pålegg og tilbehør", 15, 95.00),
    ("Leverpostei 200g", "330", "Pålegg og tilbehør", 15, 45.00),
    ("Brunost 500g", "330", "Pålegg og tilbehør", 15, 79.00),
    ("Geitost 500g", "330", "Pålegg og tilbehør", 15, 89.00),
    ("Norvegia 500g", "330", "Pålegg og tilbehør", 15, 95.00),
    ("Jarlsberg 500g", "330", "Pålegg og tilbehør", 15, 109.00),
    ("Salami skiver 200g", "330", "Pålegg og tilbehør", 15, 65.00),
    ("Spekeskinke 200g", "330", "Pålegg og tilbehør", 15, 89.00),
    ("Kokt skinke 200g", "330", "Pålegg og tilbehør", 15, 55.00),
    ("Røkelaks 200g", "330", "Pålegg og tilbehør", 15, 95.00),
    ("Kaviar tube", "330", "Pålegg og tilbehør", 15, 59.00),
    ("Makrell i tomat", "330", "Pålegg og tilbehør", 15, 39.00),
    ("Egg 12-pk", "330", "Pålegg og tilbehør", 15, 65.00),
    ("Mel hvete 2kg", "340", "Råvarer", 15, 49.00),
    ("Sukker 1kg", "340", "Råvarer", 15, 32.00),
    ("Gjær fersk 50g", "340", "Råvarer", 15, 12.00),
    ("Olje matlaging 1L", "340", "Råvarer", 15, 65.00),
    ("Salt 500g", "340", "Råvarer", 15, 25.00),
    ("Bærpose 250g", "320", "Frukt og bær", 15, 75.00),
    ("Frukt-pakke familie", "320", "Frukt og bær", 15, 195.00),
    ("Brødskjærer brett", "500", "Tilbehør", 25, 295.00),
    ("Bakepapir 50m", "500", "Tilbehør", 25, 89.00),
    ("Muffinsformer 100-pk", "500", "Tilbehør", 25, 65.00),
    ("Stearinlys 6-pk", "500", "Tilbehør", 25, 49.00),
    ("Servietter 50-pk", "500", "Tilbehør", 25, 35.00),
    ("Gavekort 200,-", "999", "Gavekort", 0, 200.00),
    ("Gavekort 500,-", "999", "Gavekort", 0, 500.00),
    ("Gavekort 1000,-", "999", "Gavekort", 0, 1000.00),
    ("Gavepose liten", "500", "Tilbehør", 25, 19.00),
    ("Gavepose stor", "500", "Tilbehør", 25, 35.00),
    ("Bærepose papir", "500", "Tilbehør", 25, 5.00),
    ("Kaffekopp pap 4dl", "500", "Tilbehør", 25, 8.00),
    ("Lunsj-eske pap", "500", "Tilbehør", 25, 12.00),
    ("Bestikk-sett pap", "500", "Tilbehør", 25, 6.00),
    ("Sukrin 250g", "340", "Råvarer", 15, 89.00),
    ("Kakaopulver 200g", "340", "Råvarer", 15, 65.00),
    ("Vaniljesukker 100g", "340", "Råvarer", 15, 39.00),
    ("Bakepulver 100g", "340", "Råvarer", 15, 25.00),
    ("Mandler 200g", "340", "Råvarer", 15, 79.00),
    ("Valnøtter 200g", "340", "Råvarer", 15, 75.00),
    ("Rosiner 250g", "340", "Råvarer", 15, 35.00),
    ("Sjokoladebiter 200g", "340", "Råvarer", 15, 65.00),
]

# Restaurant-sortiment (navn, vg1_id, vg1, vg2_id, vg2, mva, takeaway_pris)
REST = [
    # Forretter
    ("Tomatsuppe", "1", "FORRETTER", "1", "SUPPER", 15, 95.00),
    ("Fiskesuppe", "1", "FORRETTER", "1", "SUPPER", 15, 145.00),
    ("Skalldyrsuppe", "1", "FORRETTER", "1", "SUPPER", 15, 165.00),
    ("Aspargessuppe", "1", "FORRETTER", "1", "SUPPER", 15, 119.00),
    ("Bruschetta", "1", "FORRETTER", "2", "SMÅRETTER", 15, 119.00),
    ("Carpaccio okse", "1", "FORRETTER", "2", "SMÅRETTER", 15, 175.00),
    ("Reker med majones", "1", "FORRETTER", "2", "SMÅRETTER", 15, 195.00),
    ("Skagen toast", "1", "FORRETTER", "2", "SMÅRETTER", 15, 175.00),
    ("Caesar salat liten", "1", "FORRETTER", "3", "SALAT", 15, 145.00),
    ("Geitost salat", "1", "FORRETTER", "3", "SALAT", 15, 165.00),
    ("Bakt camembert", "1", "FORRETTER", "2", "SMÅRETTER", 15, 165.00),
    ("Hjortecarpaccio", "1", "FORRETTER", "2", "SMÅRETTER", 15, 195.00),
    ("Røkelaks med eggerøre", "1", "FORRETTER", "2", "SMÅRETTER", 15, 195.00),
    ("Rakfisk forrett", "1", "FORRETTER", "2", "SMÅRETTER", 15, 215.00),
    ("Spekemat tallerken", "1", "FORRETTER", "2", "SMÅRETTER", 15, 225.00),
    ("Ostetallerken", "1", "FORRETTER", "2", "SMÅRETTER", 15, 245.00),
    # Hovedretter kjøtt
    ("Indrefilet av okse", "2", "HOVEDRETTER", "4", "KJØTT", 15, 425.00),
    ("Entrecôte", "2", "HOVEDRETTER", "4", "KJØTT", 15, 395.00),
    ("Hjortefilet", "2", "HOVEDRETTER", "4", "KJØTT", 15, 445.00),
    ("Lammecarré", "2", "HOVEDRETTER", "4", "KJØTT", 15, 425.00),
    ("Reinsdyrfilet", "2", "HOVEDRETTER", "4", "KJØTT", 15, 465.00),
    ("Pinnekjøtt", "2", "HOVEDRETTER", "4", "KJØTT", 15, 365.00),
    ("Ribbe juleaften", "2", "HOVEDRETTER", "4", "KJØTT", 15, 345.00),
    ("Lapskaus", "2", "HOVEDRETTER", "4", "KJØTT", 15, 245.00),
    ("Kjøttkaker tradisjonell", "2", "HOVEDRETTER", "4", "KJØTT", 15, 225.00),
    ("Wienerschnitzel", "2", "HOVEDRETTER", "4", "KJØTT", 15, 295.00),
    ("Burger huset", "2", "HOVEDRETTER", "4", "KJØTT", 15, 265.00),
    ("Cheeseburger", "2", "HOVEDRETTER", "4", "KJØTT", 15, 245.00),
    ("Pulled pork burger", "2", "HOVEDRETTER", "4", "KJØTT", 15, 265.00),
    ("Ribs BBQ", "2", "HOVEDRETTER", "4", "KJØTT", 15, 295.00),
    ("Spareribs porsjon", "2", "HOVEDRETTER", "4", "KJØTT", 15, 295.00),
    ("Lammeskank", "2", "HOVEDRETTER", "4", "KJØTT", 15, 365.00),
    # Hovedretter fisk
    ("Torsk pannestekt", "2", "HOVEDRETTER", "5", "FISK", 15, 325.00),
    ("Kveite ovnsbakt", "2", "HOVEDRETTER", "5", "FISK", 15, 395.00),
    ("Laks pannestekt", "2", "HOVEDRETTER", "5", "FISK", 15, 295.00),
    ("Ørret bakt", "2", "HOVEDRETTER", "5", "FISK", 15, 295.00),
    ("Sei pannestekt", "2", "HOVEDRETTER", "5", "FISK", 15, 245.00),
    ("Steinbit grillet", "2", "HOVEDRETTER", "5", "FISK", 15, 325.00),
    ("Fisk og chips", "2", "HOVEDRETTER", "5", "FISK", 15, 245.00),
    ("Fiskegrateng", "2", "HOVEDRETTER", "5", "FISK", 15, 225.00),
    ("Reker hvitløk", "2", "HOVEDRETTER", "5", "FISK", 15, 295.00),
    ("Skreimølje", "2", "HOVEDRETTER", "5", "FISK", 15, 345.00),
    ("Bacalao", "2", "HOVEDRETTER", "5", "FISK", 15, 295.00),
    ("Rakfisk porsjon", "2", "HOVEDRETTER", "5", "FISK", 15, 325.00),
    # Pasta
    ("Spaghetti carbonara", "2", "HOVEDRETTER", "6", "PASTA", 15, 215.00),
    ("Spaghetti bolognese", "2", "HOVEDRETTER", "6", "PASTA", 15, 215.00),
    ("Lasagne", "2", "HOVEDRETTER", "6", "PASTA", 15, 225.00),
    ("Tagliatelle scampi", "2", "HOVEDRETTER", "6", "PASTA", 15, 245.00),
    ("Penne arrabiata", "2", "HOVEDRETTER", "6", "PASTA", 15, 195.00),
    ("Ravioli ricotta", "2", "HOVEDRETTER", "6", "PASTA", 15, 235.00),
    ("Tortellini soppsaus", "2", "HOVEDRETTER", "6", "PASTA", 15, 245.00),
    ("Risotto sopp", "2", "HOVEDRETTER", "6", "PASTA", 15, 245.00),
    ("Risotto skalldyr", "2", "HOVEDRETTER", "6", "PASTA", 15, 295.00),
    # Pizza
    ("Pizza Margherita", "2", "HOVEDRETTER", "7", "PIZZA", 15, 195.00),
    ("Pizza Pepperoni", "2", "HOVEDRETTER", "7", "PIZZA", 15, 215.00),
    ("Pizza Hawaii", "2", "HOVEDRETTER", "7", "PIZZA", 15, 215.00),
    ("Pizza Capricciosa", "2", "HOVEDRETTER", "7", "PIZZA", 15, 235.00),
    ("Pizza Quattro Stagioni", "2", "HOVEDRETTER", "7", "PIZZA", 15, 235.00),
    ("Pizza Bianca", "2", "HOVEDRETTER", "7", "PIZZA", 15, 215.00),
    ("Pizza huset", "2", "HOVEDRETTER", "7", "PIZZA", 15, 245.00),
    ("Pizza vegetar", "2", "HOVEDRETTER", "7", "PIZZA", 15, 215.00),
    ("Pizza skinke/ost", "2", "HOVEDRETTER", "7", "PIZZA", 15, 215.00),
    ("Calzone", "2", "HOVEDRETTER", "7", "PIZZA", 15, 235.00),
    # Vegetar
    ("Vegetarburger", "2", "HOVEDRETTER", "8", "VEGETAR", 15, 235.00),
    ("Falafel-tallerken", "2", "HOVEDRETTER", "8", "VEGETAR", 15, 215.00),
    ("Halloumi grillet", "2", "HOVEDRETTER", "8", "VEGETAR", 15, 245.00),
    ("Vegan curry", "2", "HOVEDRETTER", "8", "VEGETAR", 15, 215.00),
    ("Polenta sopp", "2", "HOVEDRETTER", "8", "VEGETAR", 15, 215.00),
    # Tilbehør
    ("Pommes frites", "3", "TILBEHØR", "9", "POTET", 15, 65.00),
    ("Søtpotetfries", "3", "TILBEHØR", "9", "POTET", 15, 75.00),
    ("Bakt potet", "3", "TILBEHØR", "9", "POTET", 15, 55.00),
    ("Potetmos", "3", "TILBEHØR", "9", "POTET", 15, 55.00),
    ("Råstekte poteter", "3", "TILBEHØR", "9", "POTET", 15, 55.00),
    ("Grønnsakswok", "3", "TILBEHØR", "10", "GRØNT", 15, 75.00),
    ("Dampede grønnsaker", "3", "TILBEHØR", "10", "GRØNT", 15, 65.00),
    ("Grillet asparges", "3", "TILBEHØR", "10", "GRØNT", 15, 95.00),
    ("Coleslaw", "3", "TILBEHØR", "10", "GRØNT", 15, 55.00),
    ("Grønn salat", "3", "TILBEHØR", "10", "GRØNT", 15, 55.00),
    ("Bearnaise saus", "3", "TILBEHØR", "11", "SAUS", 15, 39.00),
    ("Pepper saus", "3", "TILBEHØR", "11", "SAUS", 15, 39.00),
    ("Soppsaus", "3", "TILBEHØR", "11", "SAUS", 15, 39.00),
    ("Hvitvinsaus", "3", "TILBEHØR", "11", "SAUS", 15, 39.00),
    ("Smør med urter", "3", "TILBEHØR", "11", "SAUS", 15, 25.00),
    ("Aioli", "3", "TILBEHØR", "11", "SAUS", 15, 35.00),
    # Barneretter
    ("Barneburger", "4", "BARN", "12", "BARN", 15, 145.00),
    ("Barnespagetti", "4", "BARN", "12", "BARN", 15, 135.00),
    ("Barnefisk", "4", "BARN", "12", "BARN", 15, 145.00),
    ("Barnepølser", "4", "BARN", "12", "BARN", 15, 125.00),
    ("Barnepizza", "4", "BARN", "12", "BARN", 15, 135.00),
    ("Barneis", "4", "BARN", "12", "BARN", 15, 65.00),
    # Dessert
    ("Crème brûlée", "5", "DESSERT", "13", "DESSERT", 25, 119.00),
    ("Sjokoladefondant", "5", "DESSERT", "13", "DESSERT", 25, 125.00),
    ("Tiramisu", "5", "DESSERT", "13", "DESSERT", 25, 115.00),
    ("Pannacotta", "5", "DESSERT", "13", "DESSERT", 25, 109.00),
    ("Iskrem 3 kuler", "5", "DESSERT", "13", "DESSERT", 25, 89.00),
    ("Ostekake", "5", "DESSERT", "13", "DESSERT", 25, 119.00),
    ("Sjokoladekake", "5", "DESSERT", "13", "DESSERT", 25, 109.00),
    ("Bringebærpai", "5", "DESSERT", "13", "DESSERT", 25, 119.00),
    ("Sorbet 3 kuler", "5", "DESSERT", "13", "DESSERT", 25, 95.00),
    ("Eplekake med vaniljesaus", "5", "DESSERT", "13", "DESSERT", 25, 109.00),
    ("Frukt-tallerken", "5", "DESSERT", "13", "DESSERT", 25, 119.00),
    ("Karamellpudding", "5", "DESSERT", "13", "DESSERT", 25, 95.00),
    # Kaffe og varm drikke
    ("Espresso", "8", "VARM DRIKKE", "20", "KAFFE", 25, 39.00),
    ("Dobbel espresso", "8", "VARM DRIKKE", "20", "KAFFE", 25, 49.00),
    ("Cappuccino", "8", "VARM DRIKKE", "20", "KAFFE", 25, 49.00),
    ("Caffè latte", "8", "VARM DRIKKE", "20", "KAFFE", 25, 55.00),
    ("Americano", "8", "VARM DRIKKE", "20", "KAFFE", 25, 45.00),
    ("Filterkaffe", "8", "VARM DRIKKE", "20", "KAFFE", 25, 39.00),
    ("Kaffe avec", "8", "VARM DRIKKE", "20", "KAFFE", 25, 95.00),
    ("Te", "8", "VARM DRIKKE", "21", "TE", 25, 39.00),
    ("Varm kakao", "8", "VARM DRIKKE", "21", "TE", 25, 55.00),
    ("Varm kakao m/krem", "8", "VARM DRIKKE", "21", "TE", 25, 65.00),
    ("Gløgg", "8", "VARM DRIKKE", "21", "TE", 25, 75.00),
    # Brus / vann
    ("Coca-Cola 0,33L", "9", "BRUS OG VANN", "22", "BRUS", 25, 49.00),
    ("Coca-Cola Zero 0,33L", "9", "BRUS OG VANN", "22", "BRUS", 25, 49.00),
    ("Pepsi 0,33L", "9", "BRUS OG VANN", "22", "BRUS", 25, 49.00),
    ("Pepsi Max 0,33L", "9", "BRUS OG VANN", "22", "BRUS", 25, 49.00),
    ("Sprite 0,33L", "9", "BRUS OG VANN", "22", "BRUS", 25, 49.00),
    ("Solo 0,33L", "9", "BRUS OG VANN", "22", "BRUS", 25, 49.00),
    ("Fanta 0,33L", "9", "BRUS OG VANN", "22", "BRUS", 25, 49.00),
    ("Iste fersken 0,33L", "9", "BRUS OG VANN", "22", "BRUS", 25, 55.00),
    ("Imsdal 0,33L", "9", "BRUS OG VANN", "23", "VANN", 25, 39.00),
    ("Farris 0,33L", "9", "BRUS OG VANN", "23", "VANN", 25, 45.00),
    ("Farris sitron 0,33L", "9", "BRUS OG VANN", "23", "VANN", 25, 45.00),
    ("Mineralvann med kullsyre 0,5L", "9", "BRUS OG VANN", "23", "VANN", 25, 49.00),
    ("Mineralvann uten 0,5L", "9", "BRUS OG VANN", "23", "VANN", 25, 39.00),
    # Juice
    ("Appelsinjuice 0,25L", "9", "BRUS OG VANN", "24", "JUICE", 25, 45.00),
    ("Eplejuice 0,25L", "9", "BRUS OG VANN", "24", "JUICE", 25, 45.00),
    ("Multifruktjuice 0,25L", "9", "BRUS OG VANN", "24", "JUICE", 25, 45.00),
    # Energi
    ("Red Bull 0,25L", "9", "BRUS OG VANN", "25", "ENERGI", 25, 65.00),
    ("Red Bull Sukkerfri 0,25L", "9", "BRUS OG VANN", "25", "ENERGI", 25, 65.00),
    # Husets viner / drinker
    ("Husets hvitvin glass", "10", "VIN", "30", "HVITVIN", 25, 119.00),
    ("Husets rødvin glass", "10", "VIN", "31", "RØDVIN", 25, 119.00),
    ("Husets rosévin glass", "10", "VIN", "32", "ROSÉ", 25, 119.00),
    ("Champagne glass", "10", "VIN", "33", "MUSSERENDE", 25, 145.00),
    ("Prosecco glass", "10", "VIN", "33", "MUSSERENDE", 25, 119.00),
    ("Husets hvitvin flaske", "10", "VIN", "30", "HVITVIN", 25, 525.00),
    ("Husets rødvin flaske", "10", "VIN", "31", "RØDVIN", 25, 525.00),
    ("Chardonnay flaske", "10", "VIN", "30", "HVITVIN", 25, 595.00),
    ("Sauvignon Blanc flaske", "10", "VIN", "30", "HVITVIN", 25, 595.00),
    ("Pinot Grigio flaske", "10", "VIN", "30", "HVITVIN", 25, 595.00),
    ("Riesling flaske", "10", "VIN", "30", "HVITVIN", 25, 625.00),
    ("Cabernet Sauvignon flaske", "10", "VIN", "31", "RØDVIN", 25, 625.00),
    ("Merlot flaske", "10", "VIN", "31", "RØDVIN", 25, 595.00),
    ("Pinot Noir flaske", "10", "VIN", "31", "RØDVIN", 25, 645.00),
    ("Shiraz flaske", "10", "VIN", "31", "RØDVIN", 25, 595.00),
    ("Chianti flaske", "10", "VIN", "31", "RØDVIN", 25, 595.00),
    ("Rioja flaske", "10", "VIN", "31", "RØDVIN", 25, 625.00),
    ("Champagne flaske", "10", "VIN", "33", "MUSSERENDE", 25, 895.00),
    ("Prosecco flaske", "10", "VIN", "33", "MUSSERENDE", 25, 545.00),
    # Drinker / sprit
    ("Gin Tonic", "11", "DRINKER", "40", "DRINK", 25, 145.00),
    ("Mojito", "11", "DRINKER", "40", "DRINK", 25, 155.00),
    ("Margarita", "11", "DRINKER", "40", "DRINK", 25, 155.00),
    ("Negroni", "11", "DRINKER", "40", "DRINK", 25, 155.00),
    ("Aperol Spritz", "11", "DRINKER", "40", "DRINK", 25, 145.00),
    ("Espresso Martini", "11", "DRINKER", "40", "DRINK", 25, 155.00),
    ("Whiskey sour", "11", "DRINKER", "40", "DRINK", 25, 165.00),
    ("Bloody Mary", "11", "DRINKER", "40", "DRINK", 25, 145.00),
    ("Caipirinha", "11", "DRINKER", "40", "DRINK", 25, 155.00),
    ("Old Fashioned", "11", "DRINKER", "40", "DRINK", 25, 165.00),
    ("Dry Martini", "11", "DRINKER", "40", "DRINK", 25, 155.00),
    ("Cognac 4cl", "11", "DRINKER", "41", "SPRIT", 25, 119.00),
    ("Whisky 4cl", "11", "DRINKER", "41", "SPRIT", 25, 119.00),
    ("Vodka 4cl", "11", "DRINKER", "41", "SPRIT", 25, 95.00),
    ("Rom 4cl", "11", "DRINKER", "41", "SPRIT", 25, 95.00),
    ("Akevitt 4cl", "11", "DRINKER", "41", "SPRIT", 25, 95.00),
    ("Baileys 4cl", "11", "DRINKER", "41", "SPRIT", 25, 89.00),
    ("Jägermeister 4cl", "11", "DRINKER", "41", "SPRIT", 25, 89.00),
]


def fmt(value: float) -> str:
    """Norsk tallformat med komma og non-breaking space."""
    s = f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", "\u00a0")
    return s


def main() -> None:
    with SRC.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        rows = list(reader)
    header = rows[0]
    data = rows[1:]

    ids = [r[0] for r in data]
    id_set = set(ids)

    # Finn master-IDer: en ID er "master" hvis det finnes en annen ID som starter
    # med den + minst 3 ekstra siffer (varianter er typisk master + valuekode)
    masters = set()
    variants = set()
    for mid in ids:
        if not mid or len(mid) < 3:
            continue
        for other in ids:
            if other == mid or len(other) <= len(mid):
                continue
            if other.startswith(mid) and other[len(mid):].isdigit() and len(other) - len(mid) >= 4:
                masters.add(mid)
                variants.add(other)

    drop = masters | variants
    kept = [r for r in data if r[0] not in drop]
    print(f"Totalt: {len(data)}  master: {len(masters)}  varianter: {len(variants)}  beholdt: {len(kept)}")

    bakeri_idx = 0
    rest_idx = 0
    out_rows = [header]
    for row in kept:
        # pad til full bredde
        while len(row) < len(header):
            row.append("")
        aid = row[0]
        if aid.upper().startswith("REST"):
            navn, vg1_id, vg1, vg2_id, vg2, mva, ta_pris = REST[rest_idx % len(REST)]
            rest_idx += 1
            netto = round(ta_pris / (1 + mva / 100), 2)
            row[1] = navn                              # Artikkel navn
            row[2] = aid                                # Strekkode = ID
            row[3] = "B"                                # ABC
            row[4] = "0 - Standard"                    # Sort order
            row[5] = ""                                 # Prosess lokasjon
            row[6] = "N"                                # Synlig nettbutikk
            row[7] = "Y"                                # Aktiv
            row[8] = "N"                                # Diverse
            row[9] = vg1_id
            row[10] = vg1
            row[11] = vg2_id
            row[12] = vg2
            for i in range(13, 19):
                row[i] = ""
            row[19] = ""                                # Lev ID
            row[20] = ""                                # Leverandør
            row[21] = ""                                # Serving ID
            row[22] = "0"
            row[23] = "0"
            row[24] = "0"
            row[25] = fmt(netto)                        # Nettopris
            row[26] = fmt(mva)                          # Takeaway MVA%
            row[27] = fmt(ta_pris)                      # Takeaway pris
            row[28] = fmt(0)                            # Grossistpris
            row[29] = fmt(0)                            # Grossist innpris
            row[30] = fmt(mva)                          # MVA %
            row[31] = fmt(ta_pris)                      # Pris
            row[32] = ""                                # beskrivelse
        else:
            navn, vg_id, vg, mva, pris = BAKERI[bakeri_idx % len(BAKERI)]
            bakeri_idx += 1
            netto = round(pris / (1 + mva / 100), 2) if mva else pris
            row[1] = navn
            row[2] = aid
            row[3] = "A"
            row[4] = "0 - Standard"
            row[5] = ""
            row[6] = "Y"
            row[7] = "Y"
            row[8] = "N"
            row[9] = vg_id
            row[10] = vg
            for i in range(11, 19):
                row[i] = ""
            row[19] = ""
            row[20] = ""
            row[21] = ""
            row[22] = "0"
            row[23] = "0"
            row[24] = "0"
            row[25] = fmt(netto)
            row[26] = fmt(0)
            row[27] = fmt(0)
            row[28] = fmt(0)
            row[29] = fmt(0)
            row[30] = fmt(mva)
            row[31] = fmt(pris)
            row[32] = ""
        out_rows.append(row)

    with DST.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";", lineterminator="\r\n")
        writer.writerows(out_rows)
    print(f"Skrev {DST} med {len(out_rows) - 1} varer  (bakeri: {bakeri_idx}, restaurant: {rest_idx})")


if __name__ == "__main__":
    main()
