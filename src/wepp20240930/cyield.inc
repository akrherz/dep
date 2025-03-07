
c     being include file cyield.inc

c     + + + COMMON BLOCK DESCRIPTION + + +
c     + + + INSERT DESCRIPTION HERE  + + +

      common /yield/    sumyld(ntype,mxplan),iyldct(ntype,mxplan)
     1                  ,crpyield(ntype),crpcount(ntype),avgyield(ntype)

c     + + + VARIABLE DECLARATIONS + + +

      integer           iyldct,crpcount
      real              sumyld
      real              crpyield,avgyield

c     + + + VARIABLE DEFINITIONS + + +

c     sumyld(ntype,mxplan) : summation of all yields of a particular
c                            type of crop on a particular OFE
c                            (kg/m^2)
c     iyldct(ntype,mxplan) : counter for number of times a particular
c                            type of crop is harvested on a particular
c                            OFE

c     end include file cyield.inc

