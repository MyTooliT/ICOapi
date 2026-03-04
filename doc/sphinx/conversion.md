# Value Conversion

The [`ICOtronic`](https://github.com/MyTooliT/ICOtronic) library streams the data as unsigned 16-bit integer values. To get the actual measured physical values,
we go through two conversion steps.

## Step 1: 16-bit ADC Value to Voltage

The streamed `uint16` is a direct linear map from

- an ADC value of $0$ up to ${2^{16} - 1}$ to
- a voltage value from $0$ up to $V_{ref}$ Volt.

This means we can reverse the conversion by inverting the linear map.

> We will define the coefficients $k_1$ and $d_1$ as the factor and offset of going from bit-value to voltage respectively.

As the linear map is direct and without an offset, we can set:

```{math}
d_1 &= 0\\
k_1 &= \frac{V_{ref}}{2^{16}-1} \text{in Volt}
```

> **The first conversion only depends on the used reference voltage.**

For example, if we assume a reference voltage $V_{ref}$ of 3.3 Volt then an ADC value of $2^{15}$ (roughly half of ${2^{16} - 1}$) would translate to about 1.65 Volt:

```{math}
d_1 &= 0\\
k_1 &= \frac{3.3 V}{2^{16}-1}\\
k_1 · 2^{15} + d_1 &= \frac{3.3 V}{2^{16}-1} · 2^{15} + 0 = \frac{3.3 V·{2^{15}}}{2^{16}-1} ≅ 1.65V
```

For the same reference voltage the maximum value of $2^{16} - 1$ would translate to exactly 3.3 Volt:

```{math}
k_1 · (2^{16} - 1) + d_1 = \frac{3.3 V}{2^{16}-1} · (2^{16} - 1) + 0 = \frac{3.3 V·(2^{16}-1)}{2^{16}-1} = 3.3V
```

## Step 2: Voltage to Physical Value

Each used sensor has a datasheet and associated linear coefficients to get from voltage output to the measured physical values.

- We will define $k_2$ and $d_2$ as the linear coefficients of going from voltage to physical measurement.
- We use $p_{min}$/$p_{max}$ do denote the minimum/maximum physical value (e.g. $℃$, multiples of $g_0$, Watt) and $U_{min}$/$U_{max}$ to denote the minimum/maximum voltage value.
- Please note, that we assumed $U_{min}$ is $0~V$ and $U_{max}$ is $V_{ref}$ in step 1. If that is not the case, the calculation of step 1 is false. The calculation in step 2 does (at least in theory) also take negative minimum voltage values in account.

```{math}
k_2 = \frac{p_{max} - p_{min}}{U_{max} - U_{min}}\\
d_2 = p_{max} - k_2 · U_{max}\\
y_2 = -k_2 · U + d_2
```

For example, let us assume that we map a voltage of 0 V up to 3.3 V from a physical value of $-100 · g_0$ up to a value of $100 · g_0$. Here a value of 1.65 Volt should map to $0 · g_0$:

```{math}
k_2 = \frac{100 · g_0 - (-100 · g_0)}{3.3 V - 0V} = \frac{200 · g_0}{3.3V}\\
d_2 = 100 · g_0 - \frac{200 · g_0}{3.3V} · 3.3V = 100 · g_0\\
- \frac{200 · g_0}{3.3V} · 1.65 + 100 · g_0 = - 0.5 · 200 · g_0 + 100 · g_0 = 0 · g_0
```
