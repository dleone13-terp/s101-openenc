Real quick ideas after some failures:

Start slow with only a few layers bing implemented. Make it easier to debug.

Possible test cases on the drawing instructions parsing.

Spilt each feature into their own tables for easier debugging, better seperation. Things can be combined using sql commands or something, but this would make it easier.

Possiblly get a generated map out of what s57 layers are supported as direct one-to-ones with features on s101. as opposed to the one there right now. This could Use a parser through. Actually this looks unlikely.

Possible make a full main file just to standardize the way in. Maybe factory to select the s57 parser?

Pay attention to inputs and output of every step of the way. The idea here is for the total ouput to be "openenc" however that is defined. An "openenc" for now should be both the data ad how to draw it. Defining both the data and the drawing instructions should both be seperate to sepeerate out those two things. Start simple on the drawing instructions.

Use the injested data to then make the styles, to limit the match statements to only what will be required. This may be a problem but it is unlikely.
