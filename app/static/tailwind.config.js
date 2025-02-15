//export default {
module.exports = {
  darkMode: 'selector',
  darkMode: 'class',
  content: [
    'app/templates/*.html'
    ],
  theme: {
    fill: ({ theme }) => ({
      gray: theme('colors.gray')
    })
  },
	fontFamily: {
		sans: ['Graphik', 'sans-serif'],
		serif: ['Merriweather', 'serif'],
	},
  plugins: [],
}