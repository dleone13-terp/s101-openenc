# s101-openenc

Check out rust-openenc for some thoughts on the idea of openenc as a whole.

## What Makes This Project Special

Standing on the backs of giants (and better coders than myself). Unlike Njord and my implementation of it with rust-openenc, this project will continue the trend of writing less and reusing more. Some things we will reuse:

- **Martin tileserver** for speed and ease of use. This will work well as a showcase of the power of openenc as it also has a nice webui that will display styles and sprites. (carried from rust-openenc)
- **S-101 Portrayal Catalog** so I don't have to go through and write every style myself. This will also keep this project on track with the single source of truth for these things, IHO themselves.

- **MVT and Mapboxstyle** as the frontend ideas. These are actually not quite a part of openenc itself, but are important for my intended use case. Hopefully with these the performance of this system will be exceptional, with very little requirements.

## Architecture in my head

rust-openenc goes into this a lot, but here is the idea:

Data Pipeline:
Layer Data from binary ENC -> Probably some form of geojson in the program -> PostGIS

Conditional Styling Pipeline:
Layer Data from binary ENC -> Portrayal Catalog (Lua) -> Drawing Instructions String -> Seperate style fields in PostGIS table

Mapbox styling:
For each day/dusk/night schemes:

- Make sprites into mapbox compatible .png and json tables.
- Make style.json from color xml tables.

## Principles:

Heavy lifting should be done at injest. Everything else should be as easy as downloading MVT and displaying them like regular.

## AI Usage

I use LLMs heavily, and this project I will be trying to document it a little just in case the architecture gets too crazy.

## Development

Dev containers are used in this project, just for the postgis and adminer dependencies really. The python versions do help a bit but thats not as big of a deal.

### Dev Container

Should be simple, but it is worth noting that the dev container works by building GDAL from source. This takes a while, but so far is the best solution I have found. I do think that production would be something else in the end though, likely the GDAL official images which already have python.

