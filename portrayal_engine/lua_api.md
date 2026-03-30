# Portrayal  API

Taken from the s-100_5.2.0_final document.

## Data Access Functions (Part 13)

These functions allow the scripting environment to access data the host has loaded from a dataset, including features, spatials, attribute values, and information associations.

```lua
-- Returns a Lua array containing all of the feature IDs in the dataset.
string[] HostGetFeatureIDs()

-- Returns the feature type code (from the Feature Catalogue) for the feature instance identified by featureID.
string HostFeatureGetCode(string featureID)

-- Returns a Lua array containing all of the information type IDs in the dataset.
string[] HostGetInformationTypeIDs()

-- Returns the information type code for the information type instance identified by informationTypeID.
string HostInformationTypeGetCode(string informationTypeID)

-- Performs a simple attribute lookup at the given path for the specified feature instance.
-- Returns the textual representation of each attribute value in an array.
string[] HostFeatureGetSimpleAttribute(string featureID, path path, string attributeCode)

-- Returns the number of matching complex attributes that exist at the given path for the feature instance.
integer HostFeatureGetComplexAttributeCount(string featureID, path path, string attributeCode)

-- Returns a Lua array containing all of the spatial associations for the given feature instance.
SpatialAssociation[] HostFeatureGetSpatialAssociations(string featureID)

-- Returns an array containing the feature IDs associated with the given feature instance 
-- that match the requested associationCode and optional roleCode.
string[] HostFeatureGetAssociatedFeatureIDs(string featureID, string associationCode, variant roleCode)

-- Returns an array containing the information IDs associated with the given feature instance 
-- that match the requested associationCode and optional roleCode.
string[] HostFeatureGetAssociatedInformationIDs(string featureID, string associationCode, variant roleCode)

-- Returns an array containing the information IDs associated with the given information instance 
-- that match the requested associationCode and optional roleCode.
string[] HostInformationGetAssociatedInformationIDs(string informationID, string associationCode, variant roleCode)

-- Returns a Lua array containing all of the spatial IDs in the dataset.
string[] HostGetSpatialIDs()

-- Queries the host for a given spatial object and returns it.
Spatial HostGetSpatial(string spatialID)

-- Returns an array containing the information IDs for the given spatial instance 
-- that match the associationCode and optional roleCode. Returns nil if invalid.
variant HostSpatialGetAssociatedInformationIDs(string spatialID, string associationCode, variant roleCode)

-- Returns an array of all feature instances that reference the given spatial object.
string[] HostSpatialGetAssociatedFeatureIDs(string spatialID)

-- Performs a simple attribute lookup at the indicated path for the specified information instance.
string[] HostInformationTypeGetSimpleAttribute(string informationTypeID, path path, string attributeCode)

-- Returns the number of matching complex attributes that exist at the given path for the information instance.
integer HostInformationTypeGetComplexAttributeCount(string informationTypeID, path path, string attributeCode)

```

## Type Information Access Functions (Part 13)

These functions allow the scripting environment to query the host for type information from the Feature Catalogue for any entity.

```lua
-- Returns an array containing all feature type codes defined in the Feature Catalogue.
string[] HostGetFeatureTypeCodes()

-- Returns an array containing all information type codes defined in the Feature Catalogue.
string[] HostGetInformationTypeCodes()

-- Returns an array containing all simple attribute type codes defined in the Feature Catalogue.
string[] HostGetSimpleAttributeTypeCodes()

-- Returns an array containing all complex attribute type codes defined in the Feature Catalogue.
string[] HostGetComplexAttributeTypeCodes()

-- Returns an array containing all role type codes defined in the Feature Catalogue.
string[] HostGetRoleTypeCodes()

-- Returns an array containing all information association type codes defined in the Feature Catalogue.
string[] HostGetInformationAssociationTypeCodes()

-- Returns an array containing all feature association type codes defined in the Feature Catalogue.
string[] HostGetFeatureAssociationTypeCodes()

-- Returns the Lua data structure defining the requested Feature Type.
FeatureType HostGetFeatureTypeInfo(string featureCode)

-- Returns the Lua data structure defining the requested Information Type.
InformationType HostGetInformationTypeInfo(string informationCode)

-- Returns the Lua data structure defining the requested Simple Attribute.
SimpleAttribute HostGetSimpleAttributeTypeInfo(string attributeCode)

-- Returns the Lua data structure defining the requested Complex Attribute.
ComplexAttribute HostGetComplexAttributeTypeInfo(string attributeCode)

-- Returns the Lua data structure defining the requested Role.
Role HostGetRoleTypeInfo(string roleCode)

-- Returns the Lua data structure defining the requested Information Association.
InformationAssociation HostGetInformationAssociationTypeInfo(string informationAssociationCode)

-- Returns the Lua data structure defining the requested Feature Association.
FeatureAssociation HostGetFeatureAssociationTypeInfo(string featureAssociationCode)
```

## Spatial Operations & Debugger Support Functions (Part 13)

These functions handle geometric relational testing and optional debugging hooks.

```lua
-- Returns true if the geometries represented by the two spatials relate 
-- as specified by the DE-9IM intersection matrix string.
boolean HostSpatialRelate(string spatialID1, string spatialID2, string intersectionPatternMatrix)

-- Optional implementation: Allows the script to interact with a debugger running on the host. 
-- debugAction can be 'break', 'trace', 'start_performance', 'stop_performance', or 'first_chance_error'.
void HostDebuggerEntry(string debugAction, variant parameters)
```

## Portrayal Domain-Specific Host Functions (Part 9a)

This function augments the standard host functions specifically for the Portrayal domain. It is how the generated drawing instructions are passed from the Lua script back to the host system.

```lua
This function augments the standard host functions specifically for the Portrayal domain. It is how the generated drawing instructions are passed from the Lua script back to the host system.
```