'''
Date: 2024-01-15 21:27:44
LastEditors: Jiaqi Gu && jiaqigu@asu.edu
LastEditTime: 2024-10-01 14:08:23
FilePath: /ONN_Reliable/core/models/layers/activation.py
'''
"""
Description:
Author: Jiaqi Gu (jqgu@utexas.edu)
Date: 2021-10-24 16:29:09
LastEditors: Jiaqi Gu (jqgu@utexas.edu)
LastEditTime: 2021-10-24 16:29:10
"""

from torch import nn

__all__ = ["ReLUN"]


class ReLUN(nn.Hardtanh):
    r"""Applies the element-wise function:

    .. math::
        \text{ReLUN}(x) = \min(\max(0,x), N)

    Args:
        inplace: can optionally do the operation in-place. Default: ``False``

    Shape:
        - Input: :math:`(N, *)` where `*` means, any number of additional
          dimensions
        - Output: :math:`(N, *)`, same shape as the input

    .. image:: scripts/activation_images/ReLU6.png

    Examples::

        >>> m = nn.ReLUN(N)
        >>> input = torch.randn(2)
        >>> output = m(input)
    """

    def __init__(self, N, inplace=False):
        super(ReLUN, self).__init__(0.0, N, inplace)

    def extra_repr(self):
        inplace_str = "inplace" if self.inplace else ""
        return inplace_str
